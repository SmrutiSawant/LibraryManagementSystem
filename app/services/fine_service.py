from datetime import date
#from sqlalchemy import text
from app.extensions import db
from app.models.transaction import Transaction
from app.models.fine import Fine
from app.models.member import Member
from app.models.library import Library


# ── Exceptions ────────────────────────────────────────────────────────────────

class FineError(Exception):
    """Raised for all fine-related failures."""
    pass


# ── Fine calculation helper ───────────────────────────────────────────────────

def calculate_fine_amount(days_overdue, daily_fine_amount, late_fee_cap):
    """
    amount = min(days_overdue * daily_fine_amount, late_fee_cap)
    """
    raw = days_overdue * float(daily_fine_amount)
    return min(raw, float(late_fee_cap))


# ── Create fine for a single transaction ─────────────────────────────────────

def create_fine_for_transaction(txn, member):
    """
    Called by circulation_service.return_book() when a copy
    is returned overdue.

    - Checks no fine already exists for this transaction
    - Calculates amount from library's fine settings
    - Creates Fine record
    - Updates member.current_fines
    - Auto-suspends member if current_fines > 500
    - Does NOT commit — caller (return_book) owns the transaction
    """
    # ── Guard: no duplicate fine per transaction ──────────────────────────────
    ##checks for existing fines
    existing = Fine.query.filter_by(
        transaction_id = txn.id,
        reason         = "Overdue"
    ).first()
    if existing:
        return existing  # already fined, skip silently

    # ── Get library fine settings ─────────────────────────────────────────────
    library = Library.query.get(txn.library_id)
    if not library:
        raise FineError("Library not found for this transaction.")

    days_overdue = txn.days_overdue()
    if days_overdue <= 0:
        return None  # not actually overdue

    amount = calculate_fine_amount(
        days_overdue      = days_overdue,
        daily_fine_amount = library.daily_fine_amount,
        late_fee_cap      = library.late_fee_cap,
    )

    # ── Create fine record ────────────────────────────────────────────────────
    fine = Fine(
        member_id      = member.id,
        transaction_id = txn.id,
        reason         = "Overdue",
        amount         = amount,
        calculated_on  = date.today(),
        status         = "Pending",
    )
    db.session.add(fine)
    db.session.flush()  # get fine.id without committing

    # ── Update member.current_fines ───────────────────────────────────────────
    member.current_fines = float(member.current_fines or 0) + amount

    # ── Auto-suspend if fines exceed 500 ─────────────────────────────────────
    if member.current_fines > 500:
        member.status = "Suspended"

    return fine


# ── Daily cron: process all overdue transactions ──────────────────────────────

def process_overdue_fines():
    """
    Runs at 2 AM daily via APScheduler.

    For every Active transaction past its due_date:
    1. Skip if a Fine already exists for it
    2. Calculate fine amount
    3. Create Fine record
    4. Mark transaction as Overdue
    5. Update member.current_fines
    6. Auto-suspend member if fines > 500
    7. Send overdue email
    """
    from app.services.email_service import send_overdue_email

    today = date.today()

    # ── Fetch all active overdue transactions ─────────────────────────────────
    overdue_txns = Transaction.query.filter(
        Transaction.status   == "Active",
        Transaction.due_date <  today,
    ).all()

    if not overdue_txns:
        print(f"[{today}] No overdue transactions found.")
        return

    print(f"[{today}] Processing {len(overdue_txns)} overdue transactions...")

    processed = 0
    skipped   = 0
    errors    = 0

    for txn in overdue_txns:
        try:
            # ── Skip if already fined ─────────────────────────────────────────
            existing = Fine.query.filter_by(
                transaction_id = txn.id,
                reason         = "Overdue"
            ).first()
            if existing:
                skipped += 1
                continue

            # ── Get library + member ──────────────────────────────────────────
            library = Library.query.get(txn.library_id)
            member  = Member.query.get(txn.member_id)

            if not library or not member:
                errors += 1
                continue

            # ── Calculate amount ──────────────────────────────────────────────
            days_overdue = txn.days_overdue()
            amount = calculate_fine_amount(
                days_overdue      = days_overdue,
                daily_fine_amount = library.daily_fine_amount,
                late_fee_cap      = library.late_fee_cap,
            )

            # ── Create fine ───────────────────────────────────────────────────
            fine = Fine(
                member_id      = member.id,
                transaction_id = txn.id,
                reason         = "Overdue",
                amount         = amount,
                calculated_on  = today,
                status         = "Pending",
            )
            db.session.add(fine)

            # ── Mark transaction Overdue ──────────────────────────────────────
            txn.mark_overdue()

            # ── Update member fines + auto-suspend ────────────────────────────
            member.current_fines = float(member.current_fines or 0) + amount
            if member.current_fines > 500:
                member.status = "Suspended"

            # ── Commit this transaction individually ──────────────────────────
            # Each txn commits separately so one failure doesn't block others
            db.session.commit()
            processed += 1

            # ── Send overdue email ──────────────────────────────
            try:
                send_overdue_email(member, fine, days_overdue)
            except Exception as email_err:
                print(f"  Email failed for {member.email}: {email_err}")

        except Exception as e:
            db.session.rollback()
            errors += 1
            print(f"  Error processing txn {txn.txn_code}: {e}")

    print(
        f"[{today}] Done — "
        f"processed: {processed}, "
        f"skipped: {skipped}, "
        f"errors: {errors}"
    )