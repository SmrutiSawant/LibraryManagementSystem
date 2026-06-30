import uuid
from app.extensions import db


class Library(db.Model):
    __tablename__ = "libraries"

    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Core fields 
    library_name        = db.Column(db.String(120), nullable=False)
    location            = db.Column(db.String(255), nullable=True)
    daily_fine_amount   = db.Column(db.Numeric(10, 2), nullable=False, default=5)
    late_fee_cap        = db.Column(db.Numeric(10, 2), nullable=False, default=100)
    is_active           = db.Column(db.Boolean, nullable=False, default=True)

    # Relationships
    book_copies  = db.relationship("BookCopy",    back_populates="library",
                                   lazy="dynamic")
    members      = db.relationship("Member",      back_populates="library",
                                   lazy="dynamic")
    transactions = db.relationship("Transaction", back_populates="library",
                                   lazy="dynamic")
    staff        = db.relationship("Staff",       back_populates="library",
                                   lazy="dynamic")

    def __repr__(self):
        return f"<Library {self.id} — {self.library_name}>"