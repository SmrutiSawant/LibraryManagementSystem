from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from app.services.circulation_service import (
    search_by_barcode,
    search_member,
    checkout_book,
    return_book,
    CirculationError,
)
from app.extensions import db

circulation_bp = Blueprint("circulation", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def success_response(data, status_code=200):
    return jsonify({"success": True, "data": data}), status_code


def librarian_required():
    """
    Returns (identity, None) on success.
    Returns (None, error_response) on failure.
    """
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "librarian":
            return None, error_response(
                "Librarian access required.", 403
            )
        return get_jwt_identity(), None  
    except Exception:
        return None, error_response(
            "Missing or invalid token.", 401
        )


def member_required():
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "member":
            return None, error_response("Member access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)


def reservation_payload(reservation):
    from app.models.book_copy import BookCopy

    available_copy = BookCopy.query.filter_by(
        book_id=reservation.book_id,
        status="Available",
    ).first()

    return {
        "id": reservation.id,
        "reservation_code": reservation.reservation_code,
        "status": reservation.status,
        "requested_at": reservation.requested_at.isoformat(),
        "processed_at": reservation.processed_at.isoformat()
                        if reservation.processed_at else None,
        "notes": reservation.notes,
        "member": {
            "id": reservation.member.id,
            "member_code": reservation.member.member_code,
            "full_name": reservation.member.full_name,
            "email": reservation.member.email,
            "status": reservation.member.status,
        } if reservation.member else None,
        "book": {
            "id": reservation.book.id,
            "book_code": reservation.book.book_code,
            "title": reservation.book.title,
            "author": reservation.book.author,
            "available_copies": reservation.book.available_copies,
        } if reservation.book else None,
        "available_copy": {
            "id": available_copy.id,
            "copy_code": available_copy.copy_code,
            "barcode": available_copy.barcode,
        } if available_copy else None,
    }


# ── POST /api/circulation/reservations — member requests books ───────────────

@circulation_bp.post("/reservations")
def create_reservations():
    identity, err = member_required()
    if err:
        return err

    from app.models.book import Book
    from app.models.reservation import Reservation

    body = request.get_json() or {}
    book_ids = body.get("book_ids") or []
    if not book_ids:
        return error_response("Choose at least one book to reserve.", 400)
    if len(book_ids) > 5:
        return error_response("You can request up to 5 books at once.", 400)

    created = []
    skipped = []
    for book_id in book_ids:
        book = Book.query.get(book_id)
        if not book:
            skipped.append({"book_id": book_id, "reason": "Book not found"})
            continue

        existing = Reservation.query.filter_by(
            member_id=identity,
            book_id=book.id,
            status="Pending",
        ).first()
        if existing:
            skipped.append({
                "book_id": book.id,
                "title": book.title,
                "reason": "Already requested",
            })
            continue

        reservation = Reservation(member_id=identity, book_id=book.id)
        db.session.add(reservation)
        created.append(reservation)

    db.session.commit()

    return success_response({
        "created": [reservation_payload(item) for item in created],
        "skipped": skipped,
    }, 201)


# ── GET /api/circulation/reservations — librarian queue ─────────────────────

@circulation_bp.get("/reservations")
def list_reservations():
    identity, err = librarian_required()
    if err:
        return err

    from app.models.reservation import Reservation

    status = request.args.get("status", "Pending").strip()
    limit = min(int(request.args.get("limit", 50)), 100)

    query = Reservation.query.order_by(Reservation.requested_at.desc())
    if status:
        query = query.filter(Reservation.status == status)

    reservations = query.limit(limit).all()
    return success_response([reservation_payload(item) for item in reservations])


# ── POST /api/circulation/reservations/<id>/approve ─────────────────────────

@circulation_bp.post("/reservations/<reservation_id>/approve")
def approve_reservation(reservation_id):
    identity, err = librarian_required()
    if err:
        return err

    from app.models.book_copy import BookCopy
    from app.models.reservation import Reservation

    reservation = Reservation.query.get(reservation_id)
    if not reservation:
        return error_response("Reservation not found.", 404)
    if reservation.status != "Pending":
        return error_response(f"Reservation is already {reservation.status}.", 400)

    copy = BookCopy.query.filter_by(
        book_id=reservation.book_id,
        status="Available",
    ).first()
    if not copy:
        return error_response("No available copy for this book.", 400)

    try:
        result = checkout_book(
            member_id=reservation.member_id,
            copy_id=copy.id,
        )
        from app.models.transaction import Transaction
        txn = Transaction.query.filter_by(txn_code=result["txn_code"]).first()
        reservation.approve(txn.id if txn else None)
        db.session.commit()
        return success_response({
            "reservation": reservation_payload(reservation),
            "checkout": result,
        })
    except CirculationError as e:
        db.session.rollback()
        return error_response(str(e), 400)


# ── POST /api/circulation/reservations/<id>/reject ──────────────────────────

@circulation_bp.post("/reservations/<reservation_id>/reject")
def reject_reservation(reservation_id):
    identity, err = librarian_required()
    if err:
        return err

    from app.models.reservation import Reservation

    reservation = Reservation.query.get(reservation_id)
    if not reservation:
        return error_response("Reservation not found.", 404)
    if reservation.status != "Pending":
        return error_response(f"Reservation is already {reservation.status}.", 400)

    body = request.get_json() or {}
    reservation.reject(body.get("notes", "").strip() or None)
    db.session.commit()

    return success_response(reservation_payload(reservation))


# ── GET /api/circulation/search/barcode?q=<barcode> ──────────────────────────

@circulation_bp.get("/search/barcode")
def barcode_search():
    """
    Librarian scans or types a barcode.
    Returns book + copy details + current transaction if checked out.
    """
    identity, err = librarian_required()  
    if err:
        return err

    barcode = request.args.get("q", "").strip()
    if not barcode:
        return error_response("Barcode query parameter 'q' is required.", 400)

    try:
        result = search_by_barcode(barcode)
        return success_response(result)
    except CirculationError as e:
        return error_response(str(e), 404)


# ── GET /api/circulation/search/member?q=<query> ─────────────────────────────

@circulation_bp.get("/search/member")
def member_search():
    """
    Librarian searches for a member by name, email, or member code.
    """
    identity, err = librarian_required()
    if err:
        return err

    query = request.args.get("q", "").strip()
    if not query:
        return error_response("Search query parameter 'q' is required.", 400)

    try:
        members = search_member(query)
        return success_response(members)
    except CirculationError as e:
        return error_response(str(e), 400)


# ── POST /api/circulation/checkout ───────────────────────────────────────────

@circulation_bp.post("/checkout")
def checkout():
    """
    Checkout a book copy to a member.
    Body: { member_id, copy_id }
    """
    identity, err = librarian_required()
    if err:
        return err

    body = request.get_json()

    # ── Validate required fields ──────────────────────────────────────────────
    required = ["member_id", "copy_id"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    try:
        result = checkout_book(
            member_id = body["member_id"],
            copy_id   = body["copy_id"],
        )
        return success_response(result, 201)
    except CirculationError as e:
        return error_response(str(e), 400)


# ── POST /api/circulation/return ─────────────────────────────────────────────

@circulation_bp.post("/return")
def return_book_route():
    """
    Return a checked out book copy.
    Body: { copy_id }
    """
    identity, err = librarian_required()
    if err:
        return err

    body = request.get_json()

    if not body.get("copy_id"):
        return error_response("Missing required field: copy_id.", 400)

    try:
        result = return_book(body["copy_id"])
        return success_response(result)
    except CirculationError as e:
        return error_response(str(e), 400)


# ── GET /api/circulation/transactions ────────────────────────────────────────

@circulation_bp.get("/transactions")
def list_transactions():
    """
    Returns today's checkouts and returns for the circulation desk.
    Optional query params:
      - status: Active / Overdue / Completed
      - limit:  number of results (default 50)
    """
    identity, err = librarian_required()
    if err:
        return err

    from app.models.transaction import Transaction
    from app.models.member import Member
    from app.models.book_copy import BookCopy
    from app.models.book import Book

    status = request.args.get("status", "").strip()
    limit  = min(int(request.args.get("limit", 50)), 100)

    query = Transaction.query.order_by(
        Transaction.checked_out_at.desc()
    )

    if status:
        query = query.filter(Transaction.status == status)

    transactions = query.limit(limit).all()

    result = []
    for txn in transactions:
        member = Member.query.get(txn.member_id)
        copy   = BookCopy.query.get(txn.book_copy_id)
        book   = Book.query.get(copy.book_id) if copy else None

        result.append({
            "txn_code"      : txn.txn_code,
            "status"        : txn.status,
            "checked_out_at": txn.checked_out_at.isoformat(),
            "due_date"      : txn.due_date.isoformat(),
            "returned_at"   : txn.returned_at.isoformat()
                              if txn.returned_at else None,
            "days_overdue"  : txn.days_overdue(),
            "member": {
                "member_code": member.member_code,
                "full_name"  : member.full_name,
            } if member else None,
            "book": {
                "title"    : book.title,
                "book_code": book.book_code,
            } if book else None,
            "copy": {
                "barcode"  : copy.barcode,
                "copy_code": copy.copy_code,
            } if copy else None,
        })

    return success_response(result)

# ── POST /api/circulation/fines — Librarian creates manual fine ───────────────

@circulation_bp.post("/fines")
def create_manual_fine():
    """
    Librarian creates a manual fine for a specific transaction.
    Body: { transaction_id, reason, amount }
    """
    identity, err = librarian_required()
    if err:
        return err

    body = request.get_json()

    required = ["transaction_id", "reason", "amount"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    reason = body["reason"]
    if reason not in ("Damage", "Lost", "Overdue"):
        return error_response(
            "Invalid reason. Must be Damage, Lost or Overdue.", 400
        )

    try:
        amount = float(body["amount"])
        if amount <= 0:
            return error_response("Amount must be greater than 0.", 400)
    except ValueError:
        return error_response("Invalid amount.", 400)

    from app.models.transaction import Transaction
    from app.models.member import Member
    from app.models.fine import Fine
    from app.extensions import db
    from datetime import date

    txn = Transaction.query.get(body["transaction_id"])
    if not txn:
        return error_response("Transaction not found.", 404)

    if txn.status == "Completed":
        return error_response(
            "Cannot raise a fine on a completed transaction.", 400
        )

    # Check for duplicate fine with same reason on same transaction
    existing = Fine.query.filter_by(
        transaction_id = txn.id,
        reason         = reason
    ).first()
    if existing:
        return error_response(
            f"A {reason} fine already exists for this transaction "
            f"({existing.fine_code}).", 409
        )

    member = Member.query.get(txn.member_id)
    if not member:
        return error_response("Member not found.", 404)

    # Create fine
    fine = Fine(
        member_id      = member.id,
        transaction_id = txn.id,
        reason         = reason,
        amount         = amount,
        calculated_on  = date.today(),
        status         = "Pending",
    )
    db.session.add(fine)

    # Update member balance
    member.current_fines = float(member.current_fines or 0) + amount

    # Auto-suspend if over 500
    if member.current_fines > 500:
        member.status = "Suspended"

    db.session.commit()

    # Send overdue email if reason is Overdue
    try:
        if reason == "Overdue":
            from app.services.email_service import send_overdue_email
            days = txn.days_overdue()
            send_overdue_email(member, fine, days)
    except Exception:
        pass

    return success_response({
        "fine_code"   : fine.fine_code,
        "member_code" : member.member_code,
        "member_name" : member.full_name,
        "reason"      : fine.reason,
        "amount"      : float(fine.amount),
        "status"      : fine.status,
        "txn_code"    : txn.txn_code,
    }, 201)


# ── GET /api/circulation/members/<member_id>/transactions ─────────────────────

@circulation_bp.get("/members/<member_id>/transactions")
def member_active_transactions(member_id):
    """
    Returns Active/Overdue transactions for a member.
    Used by the manual fine creation panel.
    """
    identity, err = librarian_required()
    if err:
        return err

    from app.models.transaction import Transaction
    from app.models.member import Member
    from app.models.book_copy import BookCopy
    from app.models.book import Book

    member = Member.query.get(member_id)
    if not member:
        return error_response("Member not found.", 404)

    txns = Transaction.query.filter(
        Transaction.member_id == member_id,
        Transaction.status.in_(["Active", "Overdue"])
    ).order_by(Transaction.checked_out_at.desc()).all()

    result = []
    for txn in txns:
        copy = BookCopy.query.get(txn.book_copy_id)
        book = Book.query.get(copy.book_id) if copy else None
        result.append({
            "id"           : txn.id,
            "txn_code"     : txn.txn_code,
            "status"       : txn.status,
            "due_date"     : txn.due_date.isoformat(),
            "days_overdue" : txn.days_overdue(),
            "book": {
                "title"    : book.title     if book else None,
                "author"   : book.author    if book else None,
                "book_code": book.book_code if book else None,
            },
            "copy": {
                "barcode"  : copy.barcode   if copy else None,
                "copy_code": copy.copy_code if copy else None,
            }
        })

    return success_response({
        "member": {
            "id"          : member.id,
            "member_code" : member.member_code,
            "full_name"   : member.full_name,
            "email"       : member.email,
            "current_fines": float(member.current_fines),
            "status"      : member.status,
        },
        "transactions": result
    })