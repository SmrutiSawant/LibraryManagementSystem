from datetime import date
from sqlalchemy import or_
from app.extensions import db
from app.models.book_copy import BookCopy
from app.models.member import Member
from app.models.transaction import Transaction
from app.models.book import Book


# ── Exceptions ────────────────────────────────────────────────────────────────

class CirculationError(Exception):
    """Raised for all circulation failures — caught in api/circulation.py."""
    pass


# ── Search ────────────────────────────────────────────────────────────────────

def search_by_barcode(barcode):
    """
    Librarian scans or types a barcode at the desk.
    Returns copy + book details + current transaction if checked out.
    """
    copy = BookCopy.query.filter_by(barcode=barcode.strip()).first()
    if not copy:
        raise CirculationError(f"No copy found with barcode '{barcode}'.")

    book = Book.query.get(copy.book_id)

    # Fetch active transaction if copy is checked out
    active_txn = None
    if copy.current_transaction_id:
        active_txn = Transaction.query.get(copy.current_transaction_id)

    result = {
        "copy": {
            "id"        : copy.id,
            "copy_code" : copy.copy_code,
            "barcode"   : copy.barcode,
            "status"    : copy.status,
            "condition" : copy.condition,
        },
        "book": {
            "id"               : book.id,
            "book_code"        : book.book_code,
            "title"            : book.title,
            "author"           : book.author,
            "isbn"             : book.isbn,
            "category"         : book.category,
            "available_copies" : book.available_copies,
            "total_copies"     : book.total_copies,
        },
        "current_transaction": None
    }

    if active_txn:
        member = Member.query.get(active_txn.member_id)
        result["current_transaction"] = {
            "txn_code"      : active_txn.txn_code,
            "status"        : active_txn.status,
            "checked_out_at": active_txn.checked_out_at.isoformat(),
            "due_date"      : active_txn.due_date.isoformat(),
            "days_overdue"  : active_txn.days_overdue(),
            "member": {
                "member_code" : member.member_code,
                "full_name"   : member.full_name,
                "email"       : member.email,
            }
        }

    return result


def search_member(query):
    """
    Librarian searches for a member by name, email, or member_code.
    Returns a list of matching members.
    """
    query = query.strip()
    if len(query) < 2:
        raise CirculationError("Search query must be at least 2 characters.")

    members = Member.query.filter(
        or_(
            Member.full_name.ilike(f"%{query}%"),
            Member.email.ilike(f"%{query}%"),
            Member.member_code.ilike(f"%{query}%"),
        )
    ).limit(10).all()

    return [
        {
            "id"             : m.id,
            "member_code"    : m.member_code,
            "full_name"      : m.full_name,
            "email"          : m.email,
            "phone"          : m.phone,
            "status"         : m.status,
            "books_borrowed" : m.books_borrowed,
            "current_fines"  : float(m.current_fines),
        }
        for m in members
    ]


# ── Checkout ──────────────────────────────────────────────────────────────────

def checkout_book(member_id, copy_id):
    """
    Full checkout flow:
    1. Validate copy is Available
    2. Validate member can checkout
    3. Create Transaction
    4. Update BookCopy status + current_transaction_id
    5. Update Member.books_borrowed
    6. Update Book.available_copies
    All in one DB transaction — rolls back if anything fails.
    """
    # ── Fetch and validate copy ───────────────────────────────────────────────
    copy = BookCopy.query.get(copy_id)
    if not copy:
        raise CirculationError("Book copy not found.")

    if not copy.is_available():
        raise CirculationError(
            f"Copy '{copy.barcode}' is currently {copy.status} "
            f"and cannot be checked out."
        )

    # ── Fetch and validate member ─────────────────────────────────────────────
    member = Member.query.get(member_id)
    if not member:
        raise CirculationError("Member not found.")

    ok, reason = member.can_checkout()
    if not ok:
        raise CirculationError(reason)

    # ── Create transaction ────────────────────────────────────────────────────
    txn = Transaction(
        member_id    = member.id,
        book_copy_id = copy.id,
        library_id   = copy.library_id,
        status       = "Active",
        # due_date and txn_code are set automatically by before_insert event
    )
    db.session.add(txn)
    db.session.flush()  # get txn.id before updating copy

    # ── Update BookCopy ───────────────────────────────────────────────────────
    copy.mark_checked_out(txn.id)

    # ── Update Member ─────────────────────────────────────────────────────────
    member.books_borrowed += 1

    # ── Update Book available_copies ──────────────────────────────────────────
    book = Book.query.get(copy.book_id)
    book.available_copies = max(0, book.available_copies - 1)

    # ── Commit everything together ────────────────────────────────────────────
    db.session.commit()

    # ── Send checkout email (after commit — don't block on email failure) ─────
    try:
        from app.services.email_service import send_checkout_email
        send_checkout_email(member, txn, book)
    except Exception:
        pass  # email failure never rolls back a successful checkout

    return {
        "txn_code"   : txn.txn_code,
        "due_date"   : txn.due_date.isoformat(),
        "book_title" : book.title,
        "member_name": member.full_name,
        "member_code": member.member_code,
    }


# ── Return ────────────────────────────────────────────────────────────────────

def return_book(copy_id):
    """
    Full return flow:
    1. Validate copy exists and is Checked Out
    2. Mark Transaction as Completed
    3. Clear BookCopy.current_transaction_id, set status Available
    4. Update Member.books_borrowed
    5. Update Book.available_copies
    All in one DB transaction.
    """
    # ── Fetch and validate copy ───────────────────────────────────────────────
    copy = BookCopy.query.get(copy_id)
    if not copy:
        raise CirculationError("Book copy not found.")

    if copy.status not in ("Checked Out", "Overdue"):
        raise CirculationError(
            f"Copy '{copy.barcode}' is not currently checked out."
        )

    # ── Fetch active transaction ──────────────────────────────────────────────
    if not copy.current_transaction_id:
        raise CirculationError(
            f"No active transaction found for copy '{copy.barcode}'."
        )

    txn = Transaction.query.get(copy.current_transaction_id)
    if not txn:
        raise CirculationError("Transaction record not found.")

    member = Member.query.get(txn.member_id)
    book   = Book.query.get(copy.book_id)

    # ── Check if overdue — fine will be created by fine_service ──────────────
    fine_created = False
    if txn.days_overdue() > 0:
        try:
            from app.services.fine_service import create_fine_for_transaction
            create_fine_for_transaction(txn, member)
            fine_created = True
        except Exception:
            pass  # fine creation failure never blocks a return

    # ── Mark transaction completed ────────────────────────────────────────────
    txn.mark_completed()

    # ── Update BookCopy ───────────────────────────────────────────────────────
    copy.mark_returned()

    # ── Update Member ─────────────────────────────────────────────────────────
    member.books_borrowed = max(0, member.books_borrowed - 1)

    # ── Update Book available_copies ──────────────────────────────────────────
    book.available_copies += 1

    # ── Commit everything together ────────────────────────────────────────────
    db.session.commit()

    # ── Send return email ─────────────────────────────────────────────────────
    try:
        from app.services.email_service import send_return_email
        send_return_email(member, txn, book, fine_created)
    except Exception:
        pass  # email failure never rolls back a successful return

    return {
        "txn_code"    : txn.txn_code,
        "returned_at" : txn.returned_at.isoformat(),
        "book_title"  : book.title,
        "member_name" : member.full_name,
        "fine_created": fine_created,
    }