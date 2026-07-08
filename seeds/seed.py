import sys #provides access to py runtine settings
import os

#adds project root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app # imports flask app factory function
from app.extensions import db
from app.services.id_generator import create_sequences

#ORM models which maps to db tables
from app.models.library import Library
from app.models.staff import Staff
from app.models.book import Book
from app.models.book_copy import BookCopy
from app.models.member import Member
from app.models.ebook_purchase import EbookPurchase
from app.models.reservation import Reservation


def seed():
    app = create_app()

    with app.app_context():

        # ── Step 1: Create all tables ─────────────────────────────────────────
        print("Creating tables...")
        db.create_all()
        print("Tables created.")

        # ── Step 2: Create Postgres sequences ────────────────────────────────
        print("Creating sequences...")
        create_sequences()
        print("Sequences created.")

        # ── Step 3: Library ───────────────────────────────────────────────────
        existing_library = Library.query.first()
        if existing_library:
            print("Library already exists — skipping.")
            library = existing_library
        else:
            library = Library(
                library_name      = "Central Branch",
                location          = "123 Main Street, Mumbai",
                daily_fine_amount = 5,
                late_fee_cap      = 100,
                is_active         = True
            )
            db.session.add(library)
            db.session.flush()  # get library.id before committing
            print(f"Library created: {library.library_name}")

        # ── Step 4: Librarian (Staff) ─────────────────────────────────────────
        existing_staff = Staff.query.filter_by(
            email="librarian@library.com"
        ).first()

        if existing_staff:
            print("Librarian already exists — skipping.")
        else:
            staff = Staff(
                full_name  = "Head Librarian",
                email      = "librarian@library.com",
                phone      = "9999999999",
                library_id = library.id,
                is_active  = True
            )
            staff.set_password("Librarian@123")
            db.session.add(staff)
            print(f"Librarian created: {staff.email} / Librarian@123")

        # ── Step 5: Books ─────────────────────────────────────────────────────
        books_data = [
    # ── Already existing (will be skipped) ───────────────────────────────────
    {
        "title"      : "Sapiens",
        "author"     : "Yuval Noah Harari",
        "isbn"       : "9780062316097",
        "category"   : "Non-fiction",
        "description": "A brief history of humankind."
    },
    {
        "title"      : "The Great Gatsby",
        "author"     : "F. Scott Fitzgerald",
        "isbn"       : "9780743273565",
        "category"   : "Fiction",
        "description": "A story of the American dream."
    },
    {
        "title"      : "Clean Code",
        "author"     : "Robert C. Martin",
        "isbn"       : "9780132350884",
        "category"   : "Textbook",
        "description": "A handbook of agile software craftsmanship."
    },

    # ── Fiction ───────────────────────────────────────────────────────────────
    {
        "title"      : "Pride and Prejudice",
        "author"     : "Jane Austen",
        "isbn"       : "9780141439518",
        "category"   : "Fiction",
        "description": "A romantic novel of manners set in rural England.",
        "cover_image": "pride_prejudice_cover.jpg"
    },
    {
        "title"      : "The Catcher in the Rye",
        "author"     : "J.D. Salinger",
        "isbn"       : "9780316769174",
        "category"   : "Fiction",
        "description": "A story of teenage alienation and loss of innocence."
    },
    {
        "title"      : "Brave New World",
        "author"     : "Aldous Huxley",
        "isbn"       : "9780060850524",
        "category"   : "Fiction",
        "description": "A dystopian novel set in a futuristic World State."
    },
    {
        "title"      : "The Lord of the Rings",
        "author"     : "J.R.R. Tolkien",
        "isbn"       : "9780618640157",
        "category"   : "Fiction",
        "description": "An epic fantasy adventure in Middle-earth.",
        "cover_image": "lord_of_the_rings_cover.jpg"
    },
    {
        "title"      : "Crime and Punishment",
        "author"     : "Fyodor Dostoevsky",
        "isbn"       : "9780140449136",
        "category"   : "Fiction",
        "description": "A psychological novel about guilt and redemption."
    },
    {
        "title"      : "The Kite Runner",
        "author"     : "Khaled Hosseini",
        "isbn"       : "9781594631931",
        "category"   : "Fiction",
        "description": "A powerful story of friendship and redemption in Afghanistan."
    },
    {
        "title"      : "Harry Potter and the Philosopher's Stone",
        "author"     : "J.K. Rowling",
        "isbn"       : "9780747532699",
        "category"   : "Fiction",
        "description": "A young boy discovers he is a wizard on his 11th birthday."
    },
    {
        "title"      : "The Da Vinci Code",
        "author"     : "Dan Brown",
        "isbn"       : "9780385504201",
        "category"   : "Fiction",
        "description": "A mystery thriller involving secret societies and religious history."
    },

    # ── Non-fiction ───────────────────────────────────────────────────────────
    {
        "title"      : "Thinking, Fast and Slow",
        "author"     : "Daniel Kahneman",
        "isbn"       : "9780374533557",
        "category"   : "Non-fiction",
        "description": "Explores the two systems that drive the way we think.",
        "cover_image": "thinking_fast_slow_cover.jpg"
    },
    {
        "title"      : "The Power of Now",
        "author"     : "Eckhart Tolle",
        "isbn"       : "9781577314806",
        "category"   : "Non-fiction",
        "description": "A guide to spiritual enlightenment through present-moment awareness."
    },
    {
        "title"      : "Educated",
        "author"     : "Tara Westover",
        "isbn"       : "9780399590504",
        "category"   : "Non-fiction",
        "description": "A memoir about a woman who grew up in a survivalist family."
    },
    {
        "title"      : "The Lean Startup",
        "author"     : "Eric Ries",
        "isbn"       : "9780307887894",
        "category"   : "Non-fiction",
        "description": "How today's entrepreneurs use continuous innovation to create success."
    },
    {
        "title"      : "Ikigai",
        "author"     : "Héctor García",
        "isbn"       : "9780143130727",
        "category"   : "Non-fiction",
        "description": "The Japanese secret to a long and happy life."
    },
    {
        "title"      : "Zero to One",
        "author"     : "Peter Thiel",
        "isbn"       : "9780804139021",
        "category"   : "Non-fiction",
        "description": "Notes on startups and how to build the future."
    },

    # ── Textbook ──────────────────────────────────────────────────────────────
    {
        "title"      : "Computer Networks",
        "author"     : "Andrew S. Tanenbaum",
        "isbn"       : "9780132126953",
        "category"   : "Textbook",
        "description": "A comprehensive introduction to computer networking."
    },
    {
        "title"      : "Operating System Concepts",
        "author"     : "Abraham Silberschatz",
        "isbn"       : "9781118063330",
        "category"   : "Textbook",
        "description": "The definitive guide to operating systems."
    },
    {
        "title"      : "Database System Concepts",
        "author"     : "Abraham Silberschatz",
        "isbn"       : "9780073523323",
        "category"   : "Textbook",
        "description": "Comprehensive coverage of database system concepts."
    },
    {
        "title"      : "Cracking the Coding Interview",
        "author"     : "Gayle McDowell",
        "isbn"       : "9780984782857",
        "category"   : "Textbook",
        "description": "189 programming questions and solutions."
    },
    {
        "title"      : "Artificial Intelligence: A Modern Approach",
        "author"     : "Stuart Russell",
        "isbn"       : "9780136042594",
        "category"   : "Textbook",
        "description": "The leading textbook in artificial intelligence."
    },

    # ── Reference ─────────────────────────────────────────────────────────────
    {
        "title"      : "Oxford English Dictionary",
        "author"     : "Oxford University Press",
        "isbn"       : "9780198611868",
        "category"   : "Reference",
        "description": "The definitive record of the English language."
    },
    {
        "title"      : "Encyclopedia of Computer Science",
        "author"     : "Anthony Ralston",
        "isbn"       : "9780470864128",
        "category"   : "Reference",
        "description": "Comprehensive reference for computer science topics."
    },
    {
        "title"      : "The Chicago Manual of Style",
        "author"     : "University of Chicago Press",
        "isbn"       : "9780226104201",
        "category"   : "Reference",
        "description": "The authoritative guide for writers and editors."
    },

    # ── General ───────────────────────────────────────────────────────────────
    {
        "title"      : "The Diary of a Young Girl",
        "author"     : "Anne Frank",
        "isbn"       : "9780553577129",
        "category"   : "General",
        "description": "The diary of a Jewish girl hiding during World War II."
    },
    {
        "title"      : "Man's Search for Meaning",
        "author"     : "Viktor Frankl",
        "isbn"       : "9780807014271",
        "category"   : "General",
        "description": "A psychiatrist's account of surviving the Holocaust."
    },
    {
        "title"      : "Wings of Fire",
        "author"     : "A.P.J. Abdul Kalam",
        "isbn"       : "9788173711466",
        "category"   : "General",
        "description": "An autobiography of India's missile man and former president."
    },
]

        #Stores created/found books.
        created_books = []
        for book_data in books_data:
            existing = Book.query.filter_by(isbn=book_data["isbn"]).first()
            if existing:
                print(f"Book already exists — skipping: {book_data['title']}")
                created_books.append(existing)
            else:
                book = Book(
                    title       = book_data["title"],
                    author      = book_data["author"],
                    isbn        = book_data["isbn"],
                    category    = book_data["category"],
                    description = book_data["description"],
                    cover_image = book_data.get("cover_image"),
                )
                db.session.add(book)
                db.session.flush()  # get book.id before creating copies
                created_books.append(book)
                print(f"Book created: {book.title}")

        # ── Step 6: BookCopies (2 copies per book) ───────────────────────────
        barcodes = [
            ("CEN-00001", "CEN-00002"),   # Sapiens
            ("CEN-00003", "CEN-00004"),   # The Great Gatsby
            ("CEN-00005", "CEN-00006"),   # Clean Code
            ("CEN-00007", "CEN-00008"),   # Pride and Prejudice
            ("CEN-00009", "CEN-00010"),   # The Catcher in the Rye
            ("CEN-00011", "CEN-00012"),   # Brave New World
            ("CEN-00013", "CEN-00014"),   # The Lord of the Rings
            ("CEN-00015", "CEN-00016"),   # Crime and Punishment
            ("CEN-00017", "CEN-00018"),   # The Kite Runner
            ("CEN-00019", "CEN-00020"),   # Harry Potter
            ("CEN-00021", "CEN-00022"),   # The Da Vinci Code
            ("CEN-00023", "CEN-00024"),   # Thinking, Fast and Slow
            ("CEN-00025", "CEN-00026"),   # The Power of Now
            ("CEN-00027", "CEN-00028"),   # Educated
            ("CEN-00029", "CEN-00030"),   # The Lean Startup
            ("CEN-00031", "CEN-00032"),   # Ikigai
            ("CEN-00033", "CEN-00034"),   # Zero to One
            ("CEN-00035", "CEN-00036"),   # Computer Networks
            ("CEN-00037", "CEN-00038"),   # Operating System Concepts
            ("CEN-00039", "CEN-00040"),   # Database System Concepts
            ("CEN-00041", "CEN-00042"),   # Cracking the Coding Interview
            ("CEN-00043", "CEN-00044"),   # AI: A Modern Approach
            ("CEN-00045", "CEN-00046"),   # Oxford English Dictionary
            ("CEN-00047", "CEN-00048"),   # Encyclopedia of Computer Science
            ("CEN-00049", "CEN-00050"),   # The Chicago Manual of Style
            ("CEN-00051", "CEN-00052"),   # The Diary of a Young Girl
            ("CEN-00053", "CEN-00054"),   # Man's Search for Meaning
            ("CEN-00055", "CEN-00056"),   # Wings of Fire
        ]

        #pairing book with the bar code id
        for book, (barcode1, barcode2) in zip(created_books, barcodes):
            for barcode in [barcode1, barcode2]:
                existing_copy = BookCopy.query.filter_by(
                    barcode=barcode
                ).first()
                if existing_copy:
                    print(f"BookCopy already exists — skipping: {barcode}")
                else:
                    copy = BookCopy(
                        book_id          = book.id,
                        library_id       = library.id,
                        barcode          = barcode,
                        status           = "Available",
                        condition        = "Good",
                    )
                    db.session.add(copy)

                    # Update book's total_copies and available_copies
                    book.total_copies     = (book.total_copies or 0) + 1
                    book.available_copies = (book.available_copies or 0) + 1

                    print(f"BookCopy created: {barcode} for '{book.title}'")

        # ── Step 7:  Member ─────────────────────────────────────────────
        existing_member = Member.query.filter_by(
            email="alice@example.com"
        ).first()

        if existing_member:
            print("Sample member already exists — skipping.")
        else:
            member = Member(
                full_name  = "Alice Verma",
                email      = "alice@example.com",
                phone      = "9876543210",
                library_id = library.id,
                status     = "Active"
            )
            member.set_password("Member@123")
            db.session.add(member)
            print(f"Sample member created: {member.email} / Member@123")

        # ── Step 8: Commit everything ─────────────────────────────────────────
        db.session.commit()
        print("\nSeed completed successfully.")
        print("\nLogin credentials:")
        print("  Librarian → librarian@library.com / Librarian@123")
        print("  Member    → alice@example.com     / Member@123")


if __name__ == "__main__":
    seed()
