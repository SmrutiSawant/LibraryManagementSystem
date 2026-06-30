import uuid
from datetime import date
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Fine(db.Model):
    __tablename__ = "fines"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — FINE-00001
    fine_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields 
    reason          = db.Column(db.String(20),     nullable=False,
                                default="Overdue")
    amount          = db.Column(db.Numeric(10, 2), nullable=False)
    calculated_on   = db.Column(db.Date,           nullable=False,
                                default=date.today)
    status          = db.Column(db.String(20),     nullable=False,
                                default="Pending")
    paid_on         = db.Column(db.Date,           nullable=True)

    # Foreign keys
    member_id      = db.Column(db.String(36), db.ForeignKey("members.id"),
                               nullable=False)
    transaction_id = db.Column(db.String(36), db.ForeignKey("transactions.id"),
                               nullable=False)

    # Relationships
    #links fine to a memeber
    member      = db.relationship("Member",      back_populates="fines")
    #links fine to a borrrowing transaction
    transaction = db.relationship("Transaction", back_populates="fines")
    #payment that settled this fine
    payment     = db.relationship("Payment",     back_populates="fine",
                                  uselist=False)

    # Composite index — member portal "my fines" query 
    #Used for advanced table settings creating composite indexes
    __table_args__ = (
        db.Index("ix_fine_member_status", "member_id", "status"),
        db.Index("ix_fine_transaction_id", "transaction_id"),
    )

    # Status helpers
    def is_pending(self) -> bool:
        return self.status == "Pending"

    def mark_paid(self):
        self.status = "Paid"
        self.paid_on = date.today()

    def mark_waived(self):
        self.status = "Waived"

    def __repr__(self):
        return f"<Fine {self.fine_code} ₹{self.amount} [{self.status}]>"


# Auto-generate fine_code before every insert
@event.listens_for(Fine, "before_insert")
def set_fine_code(mapper, connection, target):
    if not target.fine_code:
        target.fine_code = generate_code("fine")