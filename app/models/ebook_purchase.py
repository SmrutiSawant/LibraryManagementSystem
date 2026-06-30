import uuid
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class EbookPurchase(db.Model):
    __tablename__ = "ebook_purchases"

    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))
    purchase_code = db.Column(db.String(20), unique=True, nullable=True)
    member_id = db.Column(db.String(36), db.ForeignKey("members.id"),
                          nullable=False, index=True)
    book_id = db.Column(db.String(36), db.ForeignKey("books.id"),
                        nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    purchased_at = db.Column(db.DateTime, nullable=False,
                             default=datetime.utcnow)
    status = db.Column(db.String(20), nullable=False, default="Success")

    member = db.relationship("Member", back_populates="ebook_purchases")
    book = db.relationship("Book")

    __table_args__ = (
        db.UniqueConstraint("member_id", "book_id",
                            name="uq_ebook_purchase_member_book"),
    )

    def __repr__(self):
        return f"<EbookPurchase {self.purchase_code} {self.status}>"


@event.listens_for(EbookPurchase, "before_insert")
def set_purchase_code(mapper, connection, target):
    if not target.purchase_code:
        target.purchase_code = generate_code("ebook")
