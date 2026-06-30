from flask import Blueprint, request, jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from app.extensions import db
from app.models.member import Member
from app.models.transaction import Transaction
from app.models.fine import Fine
from app.models.book_copy import BookCopy
from app.models.book import Book

members_bp = Blueprint("members", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def success_response(data, status_code=200):
    return jsonify({"success": True, "data": data}), status_code


def member_required():
    """
    Verifies JWT belongs to a member.
    Returns (identity, None) on success.
    Returns (None, error_response) on failure.
    """
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "member":
            return None, error_response("Member access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)


def librarian_required():
    """
    Verifies JWT belongs to a librarian.
    Returns (identity, None) on success.
    Returns (None, error_response) on failure.
    """
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "librarian":
            return None, error_response("Librarian access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)


# ── GET /api/members/dashboard ────────────────────────────────────────────────

@members_bp.get("/dashboard")
def dashboard():
    """
    Member portal dashboard.
    Returns currently borrowed books + fines summary.
    """
    identity, err = member_required()
    if err:
        return err

    member = Member.query.get(identity)
    if not member:
        return error_response("Member not found.", 404)

    # ── Active / Overdue transactions ─────────────────────────────────────────
    active_txns = Transaction.query.filter(
        Transaction.member_id == member.id,
        Transaction.status.in_(["Active", "Overdue"])
    ).order_by(Transaction.due_date.asc()).all()

    borrowed_books = []
    for txn in active_txns:
        copy = BookCopy.query.get(txn.book_copy_id)
        book = Book.query.get(copy.book_id) if copy else None
        borrowed_books.append({
            "txn_code"      : txn.txn_code,
            "status"        : txn.status,
            "checked_out_at": txn.checked_out_at.isoformat(),
            "due_date"      : txn.due_date.isoformat(),
            "days_overdue"  : txn.days_overdue(),
            "book": {
                "title"    : book.title     if book else None,
                "author"   : book.author    if book else None,
                "book_code": book.book_code if book else None,
                "isbn"     : book.isbn      if book else None,
                "category" : book.category  if book else None,
                "cover_image": book.cover_image if book else None,
            },
            "copy": {
                "barcode"  : copy.barcode   if copy else None,
                "copy_code": copy.copy_code if copy else None,
            }
        })

    # ── Pending fines ─────────────────────────────────────────────────────────
    pending_fines = Fine.query.filter_by(
        member_id = member.id,
        status    = "Pending"
    ).order_by(Fine.calculated_on.desc()).all()

    fines_list = []
    for fine in pending_fines:
        fines_list.append({
            "fine_code"    : fine.fine_code,
            "amount"       : float(fine.amount),
            "reason"       : fine.reason,
            "status"       : fine.status,
            "calculated_on": fine.calculated_on.isoformat(),
        })

    return success_response({
        "member": {
            "member_code"     : member.member_code,
            "full_name"       : member.full_name,
            "email"           : member.email,
            "status"          : member.status,
            "member_since"    : member.member_since.isoformat(),
            "books_borrowed"  : member.books_borrowed,
            "current_fines"   : float(member.current_fines),
            "max_books_allowed": member.max_books_allowed,
        },
        "borrowed_books": borrowed_books,
        "pending_fines" : fines_list,
    })


# ── GET /api/members/history ──────────────────────────────────────────────────

@members_bp.get("/history")
def history():
    """
    Member's full borrowing history — all Completed transactions.
    """
    identity, err = member_required()
    if err:
        return err

    member = Member.query.get(identity)
    if not member:
        return error_response("Member not found.", 404)

    completed_txns = Transaction.query.filter_by(
        member_id = member.id,
        status    = "Completed"
    ).order_by(Transaction.returned_at.desc()).limit(50).all()

    history_list = []
    for txn in completed_txns:
        copy = BookCopy.query.get(txn.book_copy_id)
        book = Book.query.get(copy.book_id) if copy else None

        # Check if a fine was raised for this transaction
        fine = Fine.query.filter_by(
            transaction_id = txn.id,
            reason         = "Overdue"
        ).first()

        history_list.append({
            "txn_code"      : txn.txn_code,
            "checked_out_at": txn.checked_out_at.isoformat(),
            "due_date"      : txn.due_date.isoformat(),
            "returned_at"   : txn.returned_at.isoformat()
                              if txn.returned_at else None,
            "book": {
                "title"    : book.title     if book else None,
                "author"   : book.author    if book else None,
                "book_code": book.book_code if book else None,
            },
            "fine": {
                "fine_code": fine.fine_code,
                "amount"   : float(fine.amount),
                "status"   : fine.status,
            } if fine else None,
        })

    return success_response(history_list)


# ── GET /api/members/fines ────────────────────────────────────────────────────

@members_bp.get("/fines")
def my_fines():
    """
    All fines for the logged-in member — Pending, Paid, Waived.
    """
    identity, err = member_required()
    if err:
        return err

    member = Member.query.get(identity)
    if not member:
        return error_response("Member not found.", 404)

    fines = Fine.query.filter_by(
        member_id=member.id
    ).order_by(Fine.calculated_on.desc()).all()

    fines_list = []
    for fine in fines:
        fines_list.append({
            "fine_code"    : fine.fine_code,
            "amount"       : float(fine.amount),
            "reason"       : fine.reason,
            "status"       : fine.status,
            "calculated_on": fine.calculated_on.isoformat(),
            "paid_on"      : fine.paid_on.isoformat()
                             if fine.paid_on else None,
        })

    return success_response({
        "current_fines": float(member.current_fines),
        "fines"        : fines_list,
    })


# ── PUT /api/members/profile ──────────────────────────────────────────────────

@members_bp.put("/profile")
def update_profile():
    """
    Member updates their own phone/address.
    Email and full_name are not editable post-registration.
    """
    identity, err = member_required()
    if err:
        return err

    member = Member.query.get(identity)
    if not member:
        return error_response("Member not found.", 404)

    body = request.get_json()

    if "phone" in body:
        member.phone = body["phone"].strip() or None
    if "address" in body:
        member.address = body["address"].strip() or None

    db.session.commit()

    return success_response({
        "member_code": member.member_code,
        "full_name"  : member.full_name,
        "email"      : member.email,
        "phone"      : member.phone,
        "address"    : member.address,
    })


# ── GET /api/members — Librarian only ────────────────────────────────────────

@members_bp.get("/")
def list_members():
    """
    Librarian view — list all members with optional status filter.
    Query params:
      - status: Active / Suspended / Inactive
      - limit : default 50
    """
    identity, err = librarian_required()
    if err:
        return err

    status = request.args.get("status", "").strip()
    limit  = min(int(request.args.get("limit", 50)), 100)

    query = Member.query.order_by(Member.member_since.desc())
    if status:
        query = query.filter(Member.status == status)

    members = query.limit(limit).all()

    return success_response([
        {
            "member_code"   : m.member_code,
            "full_name"     : m.full_name,
            "email"         : m.email,
            "phone"         : m.phone,
            "status"        : m.status,
            "books_borrowed": m.books_borrowed,
            "current_fines" : float(m.current_fines),
            "member_since"  : m.member_since.isoformat(),
        }
        for m in members
    ])
