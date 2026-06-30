import uuid
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))
    reservation_code = db.Column(db.String(20), unique=True, nullable=True)
    member_id = db.Column(db.String(36), db.ForeignKey("members.id"),
                          nullable=False, index=True)
    book_id = db.Column(db.String(36), db.ForeignKey("books.id"),
                        nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Pending")
    requested_at = db.Column(db.DateTime, nullable=False,
                             default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.String(255), nullable=True)
    transaction_id = db.Column(db.String(36), db.ForeignKey("transactions.id"),
                               nullable=True)

    member = db.relationship("Member", back_populates="reservations")
    book = db.relationship("Book")
    transaction = db.relationship("Transaction")

    def approve(self, transaction_id):
        self.status = "Approved"
        self.transaction_id = transaction_id
        self.processed_at = datetime.utcnow()

    def reject(self, notes=None):
        self.status = "Rejected"
        self.notes = notes
        self.processed_at = datetime.utcnow()

    def __repr__(self):
        return f"<Reservation {self.reservation_code} [{self.status}]>"


@event.listens_for(Reservation, "before_insert")
def set_reservation_code(mapper, connection, target):
    if not target.reservation_code:
        target.reservation_code = generate_code("reservation")
