from flask import Flask, send_from_directory
from app.config import Config
from app.extensions import db, jwt, mail, scheduler, cors

def create_app():
    app = Flask(
        __name__,
        static_folder="../frontend",
        static_url_path=""
    )

    app.config.from_object(Config)

    # Initialize extensions
    db.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})

    # Import models so SQLAlchemy can resolve string relationships.
    from app.models.library import Library
    from app.models.staff import Staff
    from app.models.book import Book
    from app.models.member import Member
    from app.models.book_copy import BookCopy
    from app.models.transaction import Transaction
    from app.models.fine import Fine
    from app.models.payment import Payment
    from app.models.ebook_purchase import EbookPurchase
    from app.models.reservation import Reservation

    # Register blueprints
    from app.api.auth import auth_bp
    from app.api.circulation import circulation_bp
    from app.api.members import members_bp
    from app.api.books import books_bp
    from app.api.payments import payments_bp
    from app.api.ebooks import ebooks_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(circulation_bp, url_prefix="/api/circulation")
    app.register_blueprint(members_bp, url_prefix="/api/members")
    app.register_blueprint(books_bp, url_prefix="/api/books")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")
    app.register_blueprint(ebooks_bp, url_prefix="/api/ebooks")

    # Serve frontend
    @app.route("/")
    def home():
        from flask import make_response
        resp = make_response(send_from_directory(app.static_folder, "index.html"))
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    # Scheduler
    from app.jobs.overdue_cron import register_jobs
    import os
    if not scheduler.running and os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        register_jobs(app)
        scheduler.start()

    return app
