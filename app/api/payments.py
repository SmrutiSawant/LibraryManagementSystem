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

    if body.get("fine_id"):
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
        return error_response("Missing required field: fine_id or book_id.", 400)

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
        fine_id             = payment_entity["notes"]["fine_id"]

    except (KeyError, TypeError) as e:
        return error_response(f"Invalid webhook payload: {e}", 400)

    # ── Guard: duplicate webhook ──────────────────────────────────────────────
    existing_payment = Payment.query.filter_by(
        razorpay_payment_id=razorpay_payment_id
    ).first()
    if existing_payment:
        # Already processed — acknowledge without reprocessing
        return success_response({"received": True, "duplicate": True})

    # ── Fetch fine and member ─────────────────────────────────────────────────
    fine = Fine.query.get(fine_id)
    if not fine:
        return error_response(f"Fine {fine_id} not found.", 404)

    member = Member.query.get(fine.member_id)
    if not member:
        return error_response("Member not found.", 404)

    # ── Create Payment record ─────────────────────────────────────────────────
    payment = Payment(
        fine_id             = fine.id,
        member_id           = member.id,
        razorpay_payment_id = razorpay_payment_id,
        razorpay_order_id   = razorpay_order_id,
        amount              = amount_inr,
        status              = "Pending",
    )
    db.session.add(payment)
    db.session.flush()  # get payment.id before marking success

    # ── Mark payment success + generate receipt ───────────────────────────────
    payment.mark_success()

    # ── Mark fine as paid ─────────────────────────────────────────────────────
    fine.mark_paid()

    # ── Update member.current_fines ───────────────────────────────────────────
    member.current_fines = max(
        0, float(member.current_fines or 0) - float(fine.amount)
    )

    # ── Auto-unsuspend if fines cleared ──────────────────────────────────────
    if member.current_fines == 0 and member.status == "Suspended":
        member.status = "Active"

    # ── Commit everything ─────────────────────────────────────────────────────
    db.session.commit()

    # ── Send receipt email ────────────────────────────────────────────────────
    try:
        from app.services.email_service import send_receipt_email
        send_receipt_email(member, payment, fine)
    except Exception:
        pass  # email never blocks payment confirmation

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
