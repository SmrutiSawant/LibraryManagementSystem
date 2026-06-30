import uuid
from sqlalchemy import event
from app.extensions import db
from app.services.id_generator import generate_code


class BookCopy(db.Model):
    __tablename__ = "book_copies"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Human-readable code — COPY-00001
    copy_code = db.Column(db.String(20), unique=True, nullable=True)

    # Core fields 
    barcode          = db.Column(db.String(50),  unique=True,
                                 nullable=False, index=True)
    status           = db.Column(db.String(20),  nullable=False,
                                 default="Available")
    condition        = db.Column(db.String(20),  nullable=True,
                                 default="Good")
    acquisition_date = db.Column(db.Date,        nullable=True)
    acquisition_cost = db.Column(db.Numeric(10, 2), nullable=True)

    # Foreign keys
    #link copy to a book
    book_id    = db.Column(db.String(36), db.ForeignKey("books.id"),
                           nullable=False)
    
    #links which branch owns which copy
    library_id = db.Column(db.String(36), db.ForeignKey("libraries.id"),
                           nullable=False)

    # Current active transaction — set on checkout, cleared on return
    current_transaction_id = db.Column(db.String(36),
                                       db.ForeignKey("transactions.id"),
                                       nullable=True)

    # Relationships
    book    = db.relationship("Book",    back_populates="copies")
    library = db.relationship("Library", back_populates="book_copies")

    # Partial unique index — only one Active/Overdue transaction per copy
    __table_args__ = (
        db.Index(
            "uq_active_txn_per_copy",
            "id",
            unique=True,
            postgresql_where=db.text(
                "current_transaction_id IS NOT NULL"
            )
        ),
    )

    # Status helpers
    #Checks whether the book copy is available for borrowing
    def is_available(self) -> bool:
        return self.status == "Available"

    def mark_checked_out(self, transaction_id: str):
        self.status = "Checked Out"
        self.current_transaction_id = transaction_id

    def mark_returned(self):
        self.status = "Available"
        self.current_transaction_id = None

    #Provides a readable string representation of the object
    def __repr__(self):
        return f"<BookCopy {self.copy_code} — {self.barcode} [{self.status}]>"


# Auto-generate copy_code before every insert
@event.listens_for(BookCopy, "before_insert")
def set_copy_code(mapper, connection, target):
    if not target.copy_code:
        target.copy_code = generate_code("copy")