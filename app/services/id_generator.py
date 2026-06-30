from sqlalchemy import text
from app.extensions import db

#sequennce_name, prefix, padding
SEQUENCES = {
    "member":   ("member_code_seq",  "MB",   4),
    "book":     ("book_code_seq",    "BOOK", 5),
    "copy":     ("copy_code_seq",    "COPY", 5),
    "txn":      ("txn_code_seq",     "TXN",  6),
    "fine":     ("fine_code_seq",    "FINE", 5),
    "payment":  ("payment_code_seq", "PAY",  5),
    "ebook":    ("ebook_purchase_code_seq", "EBOOK", 5),
    "reservation": ("reservation_code_seq", "RSV", 5),
}

def create_sequences():
    """
    Called once from seeds/seed.py before db.create_all().
    Creates all sequences in Postgres if they don't exist yet.
    """
    for seq_name, prefix, padding in SEQUENCES.values():
        db.session.execute(text(
            f"CREATE SEQUENCE IF NOT EXISTS {seq_name} START 1"
        ))
    db.session.commit()

def generate_code(entity: str) -> str:
    """
    Usage:
        generate_code("member")  → "MB-0001"
        generate_code("book")    → "BOOK-00001"
        generate_code("txn")     → "TXN-000001"
    """
    if entity not in SEQUENCES:
        raise ValueError(f"Unknown entity type: '{entity}'. "
                         f"Valid options: {list(SEQUENCES.keys())}")

    seq_name, prefix, padding = SEQUENCES[entity]
    next_val = db.session.execute(
        text(f"SELECT nextval('{seq_name}')")
    ).scalar()

    return f"{prefix}-{str(next_val).zfill(padding)}"
