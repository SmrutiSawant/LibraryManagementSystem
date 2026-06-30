import uuid
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class Book(db.Model):
    __tablename__ = "books"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — BOOK-00001
    book_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields
    title       = db.Column(db.String(255), nullable=False, index=True)
    author      = db.Column(db.String(255), nullable=False, index=True)
    isbn        = db.Column(db.String(20),  unique=True, nullable=True)
    category    = db.Column(db.String(50),  nullable=False, default="General")
    cover_image = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text,        nullable=True)

    # Computed fields — recalculated by circulation_service on BookCopy changes
    total_copies     = db.Column(db.Integer, default=0)
    available_copies = db.Column(db.Integer, default=0)

    # Relationships
    copies = db.relationship("BookCopy", back_populates="book",
                             lazy="dynamic")

    def __repr__(self):
        return f"<Book {self.book_code} — {self.title}>"


# Auto-generate book_code before every insert
@event.listens_for(Book, "before_insert")
def set_book_code(mapper, connection, target):
    if not target.book_code:
        target.book_code = generate_code("book")