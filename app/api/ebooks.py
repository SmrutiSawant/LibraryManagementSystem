from decimal import Decimal
from flask import Blueprint, Response, jsonify
import requests
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.book import Book
from app.models.ebook_purchase import EbookPurchase

ebooks_bp = Blueprint("ebooks", __name__)

GUTENBERG_SOURCES = {
    "9780141439518": {
        "label": "Project Gutenberg",
        "url": "https://www.gutenberg.org/cache/epub/1342/pg1342.txt",
    },
    "9780743273565": {
        "label": "Project Gutenberg",
        "url": "https://www.gutenberg.org/cache/epub/64317/pg64317.txt",
    },
    "9780140449136": {
        "label": "Project Gutenberg",
        "url": "https://www.gutenberg.org/cache/epub/2554/pg2554.txt",
    },
    "9780451524935": {
        "label": "Project Gutenberg",
        "url": "https://gutenberg.net.au/ebooks01/0100021.txt",
    },
}


def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def success_response(data, status_code=200):
    return jsonify({"success": True, "data": data}), status_code


def member_required():
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "member":
            return None, error_response("Member access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)


def ebook_price(book):
    category_prices = {
        "Fiction": Decimal("149.00"),
        "Non-fiction": Decimal("199.00"),
        "Reference": Decimal("249.00"),
        "Textbook": Decimal("299.00"),
        "General": Decimal("129.00"),
    }
    return category_prices.get(book.category, Decimal("159.00"))


def reading_minutes(book):
    # Gutenberg books mapped to their actual average reading times
    gutenberg_minutes = {
        "9780141439518": 600,   # Pride and Prejudice
        "9780743273565": 250,   # The Great Gatsby
        "9780140449136": 1000,  # Crime and Punishment
        "9780451524935": 500,   # 1984
    }
    if book.isbn in gutenberg_minutes:
        return gutenberg_minutes[book.isbn]

    # Calculate actual reading time based on word count of the chapter summaries
    from app.api.book_data import get_book_content
    try:
        chapters = get_book_content(book.isbn, book.title, book.author, book.category, book.description)
        total_words = 0
        for ch in chapters:
            total_words += len(ch.get("heading", "").split())
            total_words += len(ch.get("body", "").split())
        return max(5, round(total_words / 200))
    except Exception:
        base_minutes = {
            "Fiction": 45,
            "Non-fiction": 35,
            "Reference": 25,
            "Textbook": 60,
            "General": 30,
        }
        return base_minutes.get(book.category, 30)


def book_payload(book, owned=False, purchase=None, include_sample=False):
    source = GUTENBERG_SOURCES.get(book.isbn or "")
    payload = {
        "id": book.id,
        "book_code": book.book_code,
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn,
        "category": book.category,
        "cover_image": book.cover_image,
        "description": book.description,
        "price": float(ebook_price(book)),
        "owned": owned,
        "reading_minutes": reading_minutes(book),
        "total_copies": book.total_copies,
        "available_copies": book.available_copies,
        "full_text_available": True,
        "full_text_source": source["label"] if source else "Digital Edition",
    }
    if purchase:
        payload["purchase"] = {
            "purchase_code": purchase.purchase_code,
            "amount": float(purchase.amount),
            "purchased_at": purchase.purchased_at.isoformat(),
            "status": purchase.status,
        }
    if include_sample:
        payload["sample"] = build_sample(book)
    return payload


def build_sample(book):
    description = book.description or (
        f"A curated digital edition of {book.title} by {book.author}."
    )
    return [
        {
            "heading": "Opening Note",
            "body": (
                f"{book.title} is part of the Central Library ebook shelf. "
                f"{description} This preview gives members a quick sense of "
                "the edition before purchase."
            ),
        },
        {
            "heading": "Why Readers Pick It",
            "body": (
                f"Readers looking for {book.category.lower()} titles often "
                f"choose this book for {book.author}'s clear voice, memorable "
                "ideas, and library-friendly digital access."
            ),
        },
    ]


def build_reader_content(book):
    from app.api.book_data import get_book_content
    return get_book_content(book.isbn, book.title, book.author, book.category, book.description)


@ebooks_bp.get("/catalog")
def catalog():
    identity, err = member_required()
    if err:
        return err

    purchases = EbookPurchase.query.filter_by(member_id=identity).all()
    owned = {purchase.book_id: purchase for purchase in purchases}
    books = Book.query.order_by(Book.title.asc()).all()

    return success_response([
        book_payload(book, book.id in owned, owned.get(book.id),
                     include_sample=True)
        for book in books
    ])


@ebooks_bp.get("/library")
def my_library():
    identity, err = member_required()
    if err:
        return err

    purchases = EbookPurchase.query.filter_by(
        member_id=identity,
        status="Success",
    ).order_by(EbookPurchase.purchased_at.desc()).all()

    return success_response([
        book_payload(purchase.book, True, purchase)
        for purchase in purchases
        if purchase.book
    ])


@ebooks_bp.post("/purchase/<book_id>")
def purchase(book_id):
    identity, err = member_required()
    if err:
        return err

    book = Book.query.get(book_id)
    if not book:
        return error_response("Book not found.", 404)

    existing = EbookPurchase.query.filter_by(
        member_id=identity,
        book_id=book.id,
    ).first()
    if existing:
        return success_response(book_payload(book, True, existing), 200)

    purchase_record = EbookPurchase(
        member_id=identity,
        book_id=book.id,
        amount=ebook_price(book),
        status="Success",
    )
    db.session.add(purchase_record)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = EbookPurchase.query.filter_by(
            member_id=identity,
            book_id=book.id,
        ).first()
        return success_response(book_payload(book, True, existing), 200)

    return success_response(book_payload(book, True, purchase_record), 201)


@ebooks_bp.get("/reader/<book_id>")
def reader(book_id):
    identity, err = member_required()
    if err:
        return err

    purchase_record = EbookPurchase.query.filter_by(
        member_id=identity,
        book_id=book_id,
        status="Success",
    ).first()
    if not purchase_record:
        return error_response("Purchase this ebook before reading.", 403)

    book = purchase_record.book
    return success_response({
        **book_payload(book, True, purchase_record),
        "chapters": build_reader_content(book),
    })


@ebooks_bp.get("/reader/<book_id>/text")
def reader_text(book_id):
    identity, err = member_required()
    if err:
        return err

    purchase_record = EbookPurchase.query.filter_by(
        member_id=identity,
        book_id=book_id,
        status="Success",
    ).first()
    if not purchase_record:
        return error_response("Purchase this ebook before reading.", 403)

    book = purchase_record.book
    source = GUTENBERG_SOURCES.get(book.isbn or "")
    url = source["url"] if source else None

    # Global cache for dynamic lookups
    if not hasattr(ebooks_bp, "_gutenberg_cache"):
        ebooks_bp._gutenberg_cache = {}

    if not url:
        if book.title in ebooks_bp._gutenberg_cache:
            url = ebooks_bp._gutenberg_cache[book.title]
        else:
            from urllib.parse import quote
            import json
            try:
                # Search using title and author for much higher accuracy
                query = quote(f"{book.title} {book.author}")
                search_url = f"https://gutendex.com/books/?search={query}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                res = requests.get(search_url, headers=headers, timeout=6)
                res.raise_for_status()
                data = res.json()
                results = data.get("results", [])
                if results:
                    # Look for plain text link
                    formats = results[0].get("formats", {})
                    for mime, link in formats.items():
                        if "text/plain" in mime:
                            url = link
                            break
                ebooks_bp._gutenberg_cache[book.title] = url
            except Exception:
                ebooks_bp._gutenberg_cache[book.title] = None

    if not url:
        # Fallback to local chapters text representation
        default_chapters = build_reader_content(book)
        text = "\n\n".join(f"{c['heading']}\n\n{c['body']}" for c in default_chapters)
        return Response(text, mimetype="text/plain; charset=utf-8")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=15, stream=True)
        res.raise_for_status()

        chunks = []
        try:
            for chunk in res.iter_content(chunk_size=8192):
                if chunk:
                    chunks.append(chunk)
        except Exception:
            # Catch incomplete reads / connection drops, keep whatever bytes were read!
            pass

        raw_bytes = b"".join(chunks)
        text = raw_bytes.decode("utf-8", errors="replace")

        if len(text) < 10000:
            raise ValueError("Insufficient text read from Gutenberg source.")

        # Strip Project Gutenberg headers and footers
        start_markers = [
            "*** START OF THIS PROJECT GUTENBERG EBOOK",
            "*** START OF THE PROJECT GUTENBERG EBOOK",
            "***START OF THE PROJECT GUTENBERG EBOOK",
            "*** START OF THIS PROJECT GUTENBERG",
        ]
        end_markers = [
            "*** END OF THIS PROJECT GUTENBERG EBOOK",
            "*** END OF THE PROJECT GUTENBERG EBOOK",
            "***END OF THE PROJECT GUTENBERG EBOOK",
            "*** END OF THIS PROJECT GUTENBERG",
        ]

        start_idx = -1
        for marker in start_markers:
            idx = text.find(marker)
            if idx != -1:
                line_end = text.find("\n", idx)
                if line_end != -1:
                    start_idx = line_end + 1
                else:
                    start_idx = idx + len(marker)
                break

        end_idx = -1
        for marker in end_markers:
            idx = text.find(marker)
            if idx != -1:
                end_idx = idx
                break

        if start_idx != -1 and end_idx != -1:
            text = text[start_idx:end_idx].strip()
        elif start_idx != -1:
            text = text[start_idx:].strip()
        elif end_idx != -1:
            text = text[:end_idx].strip()

    except Exception:
        # Network fallback to local chapters
        default_chapters = build_reader_content(book)
        text = "\n\n".join(f"{c['heading']}\n\n{c['body']}" for c in default_chapters)
        return Response(text, mimetype="text/plain; charset=utf-8")

    return Response(text, mimetype="text/plain; charset=utf-8")
