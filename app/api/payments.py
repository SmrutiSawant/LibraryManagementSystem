import hmac
import hashlib
from flask import Blueprint, request
from app.extensions import db
from app.models.book import Book
from app.models.fine import Fine
from app.models.member import Member
from app.models.payment import Payment
from app.utils import (
    error_response,
    success_response,
    member_required,
)

payments_bp = Blueprint("payments", __name__)


def ebook_price(book):
    category_prices = {
        "Fiction": 149.00,
        "Non-fiction": 199.00,
        "Reference": 249.00,
        "Textbook": 299.00,
        "General": 129.00,
    }
    return category_prices.get(book.category, 159.00)


# ── Razorpay signature verification ──────────────────────────────────────────
def verify_razorpay_signature(webhook_body, webhook_signature):
    import os
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return True

    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        webhook_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, webhook_signature)
# ── GET /api/payments/fines/<fine_id> — get fine details for payment ─────────

@payments_bp.get("/fines/<fine_id>")
def get_fine(fine_id):
    """
    Member fetches a single fine before initiating payment.
    Returns fine details + amount for Razorpay order creation.
    """
    identity, err = member_required()
    if err:
        return err

    fine = Fine.query.get(fine_id)
    if not fine:
        return error_response("Fine not found.", 404)

    # Members can only view their own fines
    if fine.member_id != identity:
        return error_response("Access denied.", 403)

    if fine.status != "Pending":
        return error_response(
            f"Fine is already {fine.status} and cannot be paid.", 400
        )

    return success_response({
        "fine_code"    : fine.fine_code,
        "amount"       : float(fine.amount),
        "reason"       : fine.reason,
        "status"       : fine.status,
        "calculated_on": fine.calculated_on.isoformat(),
    })


# ── POST /api/payments/create-order — create Razorpay order ──────────────────

@payments_bp.post("/create-order")
def create_order():
    """
    Member initiates payment for a fine or ebook purchase.
    Creates a Razorpay order and returns order_id to the frontend.
    Frontend uses order_id to open the Razorpay checkout modal.

    Body: { fine_id } or { book_id }
    """
    identity, err = member_required()
    if err:
        return err

    body = request.get_json() or {}

    fine = None
    book = None
    order_amount = None
    receipt = None
    notes = {"member_id": identity}
    response_payload = {}

    if body.get("pay_all_fines"):
        pending_fines = Fine.query.filter_by(member_id=identity, status="Pending").all()
        if not pending_fines:
            return error_response("No pending fines to pay.", 400)

        order_amount = sum(float(f.amount) for f in pending_fines)
        receipt = f"ALL-FINES-{identity[:8]}"
        notes.update({
            "payment_type": "all_fines",
            "fine_ids": ",".join(f.id for f in pending_fines),
            "fine_codes": ",".join(f.fine_code for f in pending_fines),
        })
        response_payload = {
            "payment_type": "all_fines",
            "amount": order_amount,
        }

    elif body.get("fine_id"):
        fine = Fine.query.get(body["fine_id"])
        if not fine:
            return error_response("Fine not found.", 404)

        if fine.member_id != identity:
            return error_response("Access denied.", 403)

        if fine.status != "Pending":
            return error_response(
                f"Fine is already {fine.status} and cannot be paid.", 400
            )

        order_amount = float(fine.amount)
        receipt = fine.fine_code
        notes.update({
            "payment_type": "fine",
            "fine_id": fine.id,
            "fine_code": fine.fine_code,
        })
        response_payload = {
            "payment_type": "fine",
            "fine_id": fine.id,
            "fine_code": fine.fine_code,
        }

    elif body.get("book_id"):
        from app.models.ebook_purchase import EbookPurchase

        book = Book.query.get(body["book_id"])
        if not book:
            return error_response("Book not found.", 404)

        existing = EbookPurchase.query.filter_by(
            member_id=identity,
            book_id=book.id,
            status="Success",
        ).first()
        if existing:
            return error_response("You already own this ebook.", 400)

        order_amount = ebook_price(book)
        receipt = f"EBOOK-{book.book_code or book.id[:8]}"
        notes.update({
            "payment_type": "ebook",
            "book_id": book.id,
            "book_code": book.book_code,
        })
        response_payload = {
            "payment_type": "ebook",
            "book_id": book.id,
            "book_code": book.book_code,
        }

    else:
        return error_response("Missing required field: fine_id, book_id, or pay_all_fines.", 400)

    # ── Create Razorpay order ─────────────────────────────────────────────────
    try:
        import razorpay
        import os

        client = razorpay.Client(
            auth=(
                os.getenv("RAZORPAY_KEY_ID"),
                os.getenv("RAZORPAY_KEY_SECRET"),
            )
        )

        # Razorpay amount is in paise (1 INR = 100 paise)
        order_data = {
            "amount"  : int(order_amount * 100),
            "currency": "INR",
            "receipt" : receipt,
            "notes"   : notes,
        }

        order = client.order.create(data=order_data)

        return success_response({
            "order_id"       : order["id"],
            "amount"         : order["amount"],
            "currency"       : order["currency"],
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID"),
            **response_payload,
        })

    except Exception as e:
        return error_response(f"Could not create payment order: {str(e)}", 500)


# ── POST /api/payments/webhook — Razorpay webhook ────────────────────────────

@payments_bp.post("/webhook")
def razorpay_webhook():
    """
    Razorpay calls this endpoint after every payment event.
    No JWT auth — Razorpay is the caller, not our frontend.
    Verified via HMAC signature instead.

    On payment.captured:
    1. Verify signature
    2. Create Payment record
    3. Mark Fine as Paid
    4. Update member.current_fines
    5. Auto-unsuspend member if fines cleared
    6. Send receipt email
    """
    # ── Verify signature ──────────────────────────────────────────────────────
    webhook_signature = request.headers.get("X-Razorpay-Signature", "")
    webhook_body      = request.get_data()  # raw bytes for HMAC

    if not verify_razorpay_signature(webhook_body, webhook_signature):
        return error_response("Invalid webhook signature.", 400)

    payload = request.get_json()

    # ── Only handle payment.captured events ──────────────────────────────────
    event = payload.get("event")
    if event != "payment.captured":
        # Acknowledge other events without processing
        return success_response({"received": True})

    # ── Extract payment details ───────────────────────────────────────────────
    try:
        payment_entity = payload["payload"]["payment"]["entity"]
        razorpay_payment_id = payment_entity["id"]
        razorpay_order_id   = payment_entity.get("order_id")
        amount_paise        = payment_entity["amount"]
        amount_inr          = amount_paise / 100
        notes               = payment_entity.get("notes") or {}
        payment_type        = notes.get("payment_type")
        member_id           = notes.get("member_id")

        if not payment_type:
            if "fine_id" in notes:
                payment_type = "fine"
            elif "book_id" in notes:
                payment_type = "ebook"
            else:
                return error_response("Unknown payment type in webhook notes.", 400)

    except (KeyError, TypeError) as e:
        return error_response(f"Invalid webhook payload: {e}", 400)

    # ── Handle Ebook Purchases ────────────────────────────────────────────────
    if payment_type == "ebook":
        from app.models.ebook_purchase import EbookPurchase
        book_id = notes.get("book_id")
        if not book_id or not member_id:
            return error_response("Missing book_id or member_id for ebook payment.", 400)

        existing = EbookPurchase.query.filter_by(member_id=member_id, book_id=book_id).first()
        if not existing:
            purchase_record = EbookPurchase(
                member_id=member_id,
                book_id=book_id,
                amount=amount_inr,
                status="Success"
            )
            db.session.add(purchase_record)
        else:
            existing.status = "Success"

        db.session.commit()
        return success_response({"received": True, "payment_type": "ebook"})

    # ── Handle Consolidated Fines (Pay All Fines) ─────────────────────────────
    elif payment_type == "all_fines":
        fine_ids_str = notes.get("fine_ids", "")
        fine_ids_list = [fid.strip() for fid in fine_ids_str.split(",") if fid.strip()]
        if not fine_ids_list or not member_id:
            return error_response("Missing fine_ids or member_id for consolidated fine payment.", 400)

        member = Member.query.get(member_id)
        if not member:
            return error_response("Member not found.", 404)

        processed_payments = []
        for fine_id in fine_ids_list:
            fine = Fine.query.get(fine_id)
            if not fine or fine.status != "Pending":
                continue

            pay_id = f"{razorpay_payment_id}_{fine.id}"
            existing_payment = Payment.query.filter_by(razorpay_payment_id=pay_id).first()
            if existing_payment:
                continue

            payment = Payment(
                fine_id             = fine.id,
                member_id           = member.id,
                razorpay_payment_id = pay_id,
                razorpay_order_id   = razorpay_order_id,
                amount              = fine.amount,
                status              = "Pending",
            )
            db.session.add(payment)
            db.session.flush()
            payment.mark_success()
            fine.mark_paid()
            processed_payments.append(payment)

        member.current_fines = 0
        if member.status == "Suspended":
            member.status = "Active"

        db.session.commit()

        for payment in processed_payments:
            try:
                from app.services.email_service import send_receipt_email
                fine = Fine.query.get(payment.fine_id)
                send_receipt_email(member, payment, fine)
            except Exception:
                pass

        return success_response({"received": True, "payment_type": "all_fines", "count": len(processed_payments)})

    # ── Handle Single Fine Payment (Existing Logic) ───────────────────────────
    elif payment_type == "fine":
        fine_id = notes.get("fine_id")
        if not fine_id:
            return error_response("Missing fine_id for single fine payment.", 400)

        existing_payment = Payment.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()
        if existing_payment:
            return success_response({"received": True, "duplicate": True})

        fine = Fine.query.get(fine_id)
        if not fine:
            return error_response(f"Fine {fine_id} not found.", 404)

        member = Member.query.get(fine.member_id)
        if not member:
            return error_response("Member not found.", 404)

        payment = Payment(
            fine_id             = fine.id,
            member_id           = member.id,
            razorpay_payment_id = razorpay_payment_id,
            razorpay_order_id   = razorpay_order_id,
            amount              = amount_inr,
            status              = "Pending",
        )
        db.session.add(payment)
        db.session.flush()

        payment.mark_success()
        fine.mark_paid()

        member.current_fines = max(0, float(member.current_fines or 0) - float(fine.amount))
        if member.current_fines == 0 and member.status == "Suspended":
            member.status = "Active"

        db.session.commit()

        try:
            from app.services.email_service import send_receipt_email
            send_receipt_email(member, payment, fine)
        except Exception:
            pass

        return success_response({
            "received"      : True,
            "payment_code"  : payment.payment_code,
            "receipt_number": payment.receipt_number,
        })


# ── GET /api/payments/history — member payment history ───────────────────────

@payments_bp.get("/history")
def payment_history():
    """
    Member views their own payment history.
    """
    identity, err = member_required()
    if err:
        return err

    payments = Payment.query.filter_by(
        member_id = identity
    ).order_by(Payment.payment_date.desc()).all()

    return success_response([
        {
            "payment_code"       : p.payment_code,
            "amount"             : float(p.amount),
            "status"             : p.status,
            "payment_date"       : p.payment_date.isoformat(),
            "receipt_number"     : p.receipt_number,
            "razorpay_payment_id": p.razorpay_payment_id,
        }
        for p in payments
    ])


@payments_bp.post("/verify")
def verify_payment():
    identity, err = member_required()
    if err:
        return err

    body = request.get_json() or {}
    razorpay_payment_id = body.get("razorpay_payment_id")
    razorpay_order_id   = body.get("razorpay_order_id")
    razorpay_signature  = body.get("razorpay_signature")

    fine_id = body.get("fine_id")
    pay_all_fines = body.get("pay_all_fines")

    if not razorpay_payment_id:
        return error_response("Missing razorpay_payment_id.", 400)

    if pay_all_fines:
        pending_fines = Fine.query.filter_by(member_id=identity, status="Pending").all()
        if not pending_fines:
            return error_response("No pending fines to pay.", 400)

        processed_payments = []
        for fine in pending_fines:
            pay_id = f"{razorpay_payment_id}_{fine.id}"
            existing = Payment.query.filter_by(razorpay_payment_id=pay_id).first()
            if existing:
                continue

            payment = Payment(
                fine_id             = fine.id,
                member_id           = identity,
                razorpay_payment_id = pay_id,
                razorpay_order_id   = razorpay_order_id,
                amount              = fine.amount,
                status              = "Pending",
            )
            db.session.add(payment)
            db.session.flush()
            payment.mark_success()
            fine.mark_paid()
            processed_payments.append(payment)

        member = Member.query.get(identity)
        if member:
            member.current_fines = 0
            if member.status == "Suspended":
                member.status = "Active"

        db.session.commit()

        for payment in processed_payments:
            try:
                from app.services.email_service import send_receipt_email
                fine = Fine.query.get(payment.fine_id)
                send_receipt_email(member, payment, fine)
            except Exception:
                pass

        return success_response({"status": "Success", "payment_type": "all_fines", "count": len(processed_payments)})

    elif fine_id:
        fine = Fine.query.get(fine_id)
        if not fine:
            return error_response("Fine not found.", 404)
        if fine.member_id != identity:
            return error_response("Access denied.", 403)

        existing = Payment.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()
        if existing:
            return success_response({"status": "Success", "payment_type": "fine"})

        payment = Payment(
            fine_id             = fine.id,
            member_id           = identity,
            razorpay_payment_id = razorpay_payment_id,
            razorpay_order_id   = razorpay_order_id,
            amount              = fine.amount,
            status              = "Pending",
        )
        db.session.add(payment)
        db.session.flush()
        payment.mark_success()
        fine.mark_paid()

        member = Member.query.get(identity)
        if member:
            member.current_fines = max(0, float(member.current_fines or 0) - float(fine.amount))
            if member.current_fines == 0 and member.status == "Suspended":
                member.status = "Active"

        db.session.commit()

        try:
            from app.services.email_service import send_receipt_email
            send_receipt_email(member, payment, fine)
        except Exception:
            pass

        return success_response({
            "status": "Success",
            "payment_type": "fine",
            "payment_code": payment.payment_code,
            "receipt_number": payment.receipt_number
        })

    return error_response("Missing fine_id or pay_all_fines flag.", 400)
