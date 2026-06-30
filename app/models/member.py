import uuid
from datetime import date, datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Member(db.Model):
    __tablename__ = "members"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — MB-0001
    member_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields
    full_name    = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(120), unique=True,
                             nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    phone        = db.Column(db.String(20),  nullable=True)
    address      = db.Column(db.String(255), nullable=True)
    member_since = db.Column(db.Date, default=date.today)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Status — Active / Suspended / Inactive
    status       = db.Column(db.String(20), nullable=False, default="Active")

    # Computed/denormalized fields — updated by circulation_service
    books_borrowed    = db.Column(db.Integer,      default=0)
    current_fines     = db.Column(db.Numeric(10, 2), default=0)
    max_books_allowed = db.Column(db.Integer,      default=5)

    # Foreign key — home branch
    library_id   = db.Column(db.String(36), db.ForeignKey("libraries.id"),
                             nullable=False)

    # Relationships
    library      = db.relationship("Library",     back_populates="members")
    transactions = db.relationship("Transaction", back_populates="member",
                                   lazy="dynamic")
    fines        = db.relationship("Fine",        back_populates="member",
                                   lazy="dynamic")
    ebook_purchases = db.relationship("EbookPurchase", back_populates="member",
                                      lazy="dynamic")
    reservations = db.relationship("Reservation", back_populates="member",
                                   lazy="dynamic")

    # Password helpers
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # Checks whether member is allowed to borrow books
    def can_checkout(self):
        if self.status != "Active":
            return False, f"Account is {self.status}"
        if self.books_borrowed >= self.max_books_allowed:
            return False, f"Limit ({self.max_books_allowed} books) reached"
        if self.current_fines > 500:
            return False, f"Outstanding fine balance ₹{self.current_fines}"
        return True, None

    def __repr__(self):
        return f"<Member {self.member_code} — {self.full_name}>"


# Auto-generate member_code before every insert
@event.listens_for(Member, "before_insert")
def set_member_code(mapper, connection, target):
    if not target.member_code:
        target.member_code = generate_code("member")
