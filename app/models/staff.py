import uuid
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db


class Staff(db.Model):
    __tablename__ = "staff"

    # Internal primary key
    id = db.Column(db.String(36), primary_key=True,
                   default=lambda: str(uuid.uuid4()))

    # Core fields
    full_name    = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(120), unique=True,
                             nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    phone        = db.Column(db.String(20), nullable=True)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    # Foreign key — which branch this librarian belongs to
    library_id   = db.Column(db.String(36), db.ForeignKey("libraries.id"),
                             nullable=False)

    # Relationships
    library      = db.relationship("Library", back_populates="staff")

    # Password helpers
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Staff {self.email}>"