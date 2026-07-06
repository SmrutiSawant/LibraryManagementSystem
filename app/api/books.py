from flask import Blueprint, request
from app.extensions import db
from app.models.book import Book
from app.models.book_copy import BookCopy
from app.models.library import Library
from app.utils import (
    error_response,
    success_response,
    librarian_required,
    any_authenticated,
)

books_bp = Blueprint("books", __name__)

VALID_CATEGORIES = ["Fiction", "Non-fiction", "Reference", "Textbook", "General"]
VALID_CONDITIONS = ["Good", "Fair", "Poor"]


# ── GET /api/books — Catalog browse ──────────────────────────────────────────

@books_bp.get("/")
def list_books():
    """
    Browse the book catalog.
    Accessible by both members and librarians.
    Query params:
      - q       : search by title or author
      - category: filter by category
      - limit   : default 20
    """
    identity, err = any_authenticated()
    if err:
        return err

    search   = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    limit    = min(int(request.args.get("limit", 20)), 100)

    query = Book.query

    if search:
        query = query.filter(
            db.or_(
                Book.title.ilike(f"%{search}%"),
                Book.author.ilike(f"%{search}%"),
            )
        )

    if category:
        if category not in VALID_CATEGORIES:
            return error_response(
                f"Invalid category. Valid options: "
                f"{', '.join(VALID_CATEGORIES)}", 400
            )
        query = query.filter(Book.category == category)

    books = query.order_by(Book.title.asc()).limit(limit).all()

    return success_response([
        {
            "id"              : b.id,
            "book_code"       : b.book_code,
            "title"           : b.title,
            "author"          : b.author,
            "isbn"            : b.isbn,
            "category"        : b.category,
            "cover_image"     : b.cover_image,
            "description"     : b.description,
            "total_copies"    : b.total_copies,
            "available_copies": b.available_copies,
        }
        for b in books
    ])


# ── GET /api/books/<book_id> ──────────────────────────────────────────────────

@books_bp.get("/<book_id>")
def get_book(book_id):
    """
    Single book detail with all its copies and their statuses.
    """
    identity, err = any_authenticated()
    if err:
        return err

    book = Book.query.get(book_id)
    if not book:
        return error_response("Book not found.", 404)

    copies = BookCopy.query.filter_by(book_id=book.id).all()

    return success_response({
        "id"              : book.id,
        "book_code"       : book.book_code,
        "title"           : book.title,
        "author"          : book.author,
        "isbn"            : book.isbn,
        "category"        : book.category,
        "cover_image"     : book.cover_image,
        "description"     : book.description,
        "total_copies"    : book.total_copies,
        "available_copies": book.available_copies,
        "copies": [
            {
                "id"       : c.id,
                "copy_code": c.copy_code,
                "barcode"  : c.barcode,
                "status"   : c.status,
                "condition": c.condition,
            }
            for c in copies
        ]
    })


# ── POST /api/books — Add new book (Librarian only) ──────────────────────────

@books_bp.post("/")
def add_book():
    """
    Librarian adds a new book to the catalog.
    Body: { title, author, isbn (opt), category, description (opt) }
    """
    identity, err = librarian_required()
    if err:
        return err

    body = request.get_json()

    required = ["title", "author", "category"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    if body["category"] not in VALID_CATEGORIES:
        return error_response(
            f"Invalid category. Valid options: "
            f"{', '.join(VALID_CATEGORIES)}", 400
        )

    # Check ISBN uniqueness if provided
    isbn = body.get("isbn", "").strip() or None
    if isbn and Book.query.filter_by(isbn=isbn).first():
        return error_response(
            f"A book with ISBN {isbn} already exists.", 409
        )

    book = Book(
        title       = body["title"].strip(),
        author      = body["author"].strip(),
        isbn        = isbn,
        category    = body["category"],
        description = body.get("description", "").strip() or None,
        total_copies     = 2,
        available_copies = 2,
    )
    db.session.add(book)
    db.session.commit()

    return success_response({
        "id"       : book.id,
        "book_code": book.book_code,
        "title"    : book.title,
        "author"   : book.author,
        "category" : book.category,
    }, 201)


# ── POST /api/books/<book_id>/copies — Add a copy (Librarian only) ───────────

@books_bp.post("/<book_id>/copies")
def add_copy(book_id):
    """
    Librarian adds a new physical copy of an existing book.
    Body: { barcode, condition (opt) }
    """
    identity, err = librarian_required()
    if err:
        return err

    book = Book.query.get(book_id)
    if not book:
        return error_response("Book not found.", 404)

    body = request.get_json()

    if not body.get("barcode"):
        return error_response("Missing required field: barcode.", 400)

    barcode = body["barcode"].strip()

    # Check barcode uniqueness
    if BookCopy.query.filter_by(barcode=barcode).first():
        return error_response(
            f"A copy with barcode '{barcode}' already exists.", 409
        )

    condition = body.get("condition", "Good")
    if condition not in VALID_CONDITIONS:
        return error_response(
            f"Invalid condition. Valid options: "
            f"{', '.join(VALID_CONDITIONS)}", 400
        )

    library = Library.query.first()

    copy = BookCopy(
        book_id    = book.id,
        library_id = library.id,
        barcode    = barcode,
        status     = "Available",
        condition  = condition,
    )
    db.session.add(copy)

    # Update book copy counts
    book.total_copies     += 1
    book.available_copies +=1

    db.session.commit()

    return success_response({
        "id"       : copy.id,
        "copy_code": copy.copy_code,
        "barcode"  : copy.barcode,
        "status"   : copy.status,
        "condition": copy.condition,
    }, 201)
