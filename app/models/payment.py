import uuid
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Payment(db.Model):
    __tablename__ = "payments"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — PAY-00001
    payment_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields 
    razorpay_payment_id = db.Column(db.String(100), unique=True,
                                    nullable=False)
    razorpay_order_id   = db.Column(db.String(100), nullable=True)
    amount              = db.Column(db.Numeric(10, 2), nullable=False)
    payment_date        = db.Column(db.DateTime, nullable=False,
                                    default=datetime.utcnow)
    status              = db.Column(db.String(20), nullable=False,
                                    default="Pending")
    receipt_number      = db.Column(db.String(50), unique=True,
                                    nullable=True)

    # Foreign keys
    #Links payment to a fine
    fine_id   = db.Column(db.String(36), db.ForeignKey("fines.id"),
                          nullable=False)
    #Links payment to member
    member_id = db.Column(db.String(36), db.ForeignKey("members.id"),
                          nullable=False)

    # Relationships
    fine   = db.relationship("Fine",   back_populates="payment")
    member = db.relationship("Member", foreign_keys=[member_id])

    # Status helpers
    def is_success(self) -> bool:
        return self.status == "Success"

    def mark_success(self):
        self.status = "Success"
        self._generate_receipt_number()

    def mark_failed(self):
        self.status = "Failed"

    def _generate_receipt_number(self):
        """
        Generates a receipt number on payment success.
        Format: RCPT-<payment_code>-<YYYYMMDD>
        e.g.  : RCPT-PAY-00001-20260622
        """
        today = datetime.utcnow().strftime("%Y%m%d")
        self.receipt_number = f"RCPT-{self.payment_code}-{today}"

    def __repr__(self):
        return f"<Payment {self.payment_code} ₹{self.amount} [{self.status}]>"


# Auto-generate payment_code before every insert
@event.listens_for(Payment, "before_insert")
def set_payment_code(mapper, connection, target):
    if not target.payment_code:
        target.payment_code = generate_code("payment")