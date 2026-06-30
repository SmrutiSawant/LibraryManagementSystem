import uuid
from datetime import datetime, date, timedelta
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Transaction(db.Model):
    __tablename__ = "transactions"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — TXN-000001
    txn_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields 
    checked_out_at = db.Column(db.DateTime, nullable=False,
                               default=datetime.utcnow)
    due_date       = db.Column(db.Date,     nullable=False)
    returned_at    = db.Column(db.DateTime, nullable=True)
    status         = db.Column(db.String(20), nullable=False,
                               default="Active")
    notes          = db.Column(db.String(255), nullable=True)

    # Foreign keys
    member_id    = db.Column(db.String(36), db.ForeignKey("members.id"),
                             nullable=False)
    book_copy_id = db.Column(db.String(36), db.ForeignKey("book_copies.id"),
                             nullable=False)
    library_id   = db.Column(db.String(36), db.ForeignKey("libraries.id"),
                             nullable=False)

    # Relationships
    member   = db.relationship("Member",   back_populates="transactions")
    book_copy = db.relationship("BookCopy", foreign_keys=[book_copy_id])
    library  = db.relationship("Library",  back_populates="transactions")
    fines    = db.relationship("Fine",     back_populates="transaction",
                               lazy="dynamic")

    # Composite index for daily cron query — status + due_date
    __table_args__ = (
        db.Index("ix_txn_status_due_date", "status", "due_date"),
        db.Index("ix_txn_member_id", "member_id"),
    )

    # Status helpers
    def is_active(self) -> bool:
        return self.status == "Active"

    def is_overdue(self) -> bool:
        return self.status == "Overdue"

    def mark_overdue(self):
        self.status = "Overdue"

    def mark_completed(self):
        self.status = "Completed"
        self.returned_at = datetime.utcnow()

    def days_overdue(self) -> int:
        if self.due_date < date.today():
            return (date.today() - self.due_date).days
        return 0

    def __repr__(self):
        return f"<Transaction {self.txn_code} [{self.status}]>"


# Auto-generate txn_code + due_date before every insert
@event.listens_for(Transaction, "before_insert")
def set_txn_defaults(mapper, connection, target):
    if not target.txn_code:
        target.txn_code = generate_code("txn")
    if not target.due_date:
        target.due_date = date.today() + timedelta(days=14)