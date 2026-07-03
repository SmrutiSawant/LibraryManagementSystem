from datetime import datetime
from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models.staff import Staff
from app.models.member import Member


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthError(Exception):
    """Raised for all auth failures — caught in api/auth.py and returned as 401."""
    pass


# ── Registration ──────────────────────────────────────────────────────────────

def register_member(full_name, email, password, phone=None, address=None):
    """
    Self-registration flow for Members only.
    Staff accounts are created via seeds/seed.py — not this function.
    """
    # Check email not already taken by a member or staff
    if Member.query.filter_by(email=email).first():
        raise AuthError("An account with this email already exists.")

    if Staff.query.filter_by(email=email).first():
        raise AuthError("This email is already in use.")

    # Get the single library (single-branch MVP)
    from app.models.library import Library
    library = Library.query.first()
    if not library:
        raise AuthError("No library configured. Contact the administrator.")

    member = Member(
        full_name  = full_name,
        email      = email.lower().strip(),
        phone      = phone,
        address    = address,
        library_id = library.id,
        status     = "Active"
    )
    member.set_password(password)

    db.session.add(member)
    db.session.commit()

    return member


# ── Login ─────────────────────────────────────────────────────────────────────

def login(email, password):
    """
    Accepts email + password.
    Checks Staff table first, then Member table.
    Returns a JWT token + role + basic profile on success.
    Raises AuthError on any failure.
    """
    email = email.lower().strip()

    # ── Try Staff first ───────────────────────────────────────────────────────
    staff = Staff.query.filter_by(email=email).first()
    if staff:
        if not staff.is_active:
            raise AuthError("Your account has been deactivated. "
                            "Contact the administrator.")
        if not staff.check_password(password):
            raise AuthError("Invalid email or password.")

        token = create_access_token(
            identity=staff.id,
            additional_claims={
                "role"      : "librarian",
                "full_name" : staff.full_name,
                "email"     : staff.email,
            }
        )
        return {
            "token"     : token,
            "role"      : "librarian",
            "id"        : staff.id,
            "full_name" : staff.full_name,
            "email"     : staff.email,
        }

    # ── Try Member ────────────────────────────────────────────────────────────
    member = Member.query.filter_by(email=email).first()
    if member:
        if not member.check_password(password):
            raise AuthError("Invalid email or password.")

        # Suspended members can still log in — they just can't checkout
        # The portal shows their fines and lets them pay
        if member.status == "Inactive":
            raise AuthError("Your account is inactive. "
                            "Contact the library.")

        token = create_access_token(
            identity=member.id,
            additional_claims={
                "role"        : "member",
                "full_name"   : member.full_name,
                "email"       : member.email,
                "member_code" : member.member_code,
            }
        )
        return {
            "token"       : token,
            "role"        : "member",
            "id"          : member.id,
            "full_name"   : member.full_name,
            "email"       : member.email,
            "member_code" : member.member_code,
            "status"      : member.status,
        }

    # ── No match found ────────────────────────────────────────────────────────
    raise AuthError("Invalid email or password.")


# ── Token identity helpers ────────────────────────────────────────────────────

def get_current_staff(identity):
    """
    Given a JWT identity (UUID), returns the Staff object.
    Used in route decorators that require librarian role.
    """
    staff = Staff.query.get(identity)
    if not staff or not staff.is_active:
        raise AuthError("Librarian account not found or inactive.")
    return staff


def get_current_member(identity):
    """
    Given a JWT identity (UUID), returns the Member object.
    Used in route decorators that require member role.
    """
    member = Member.query.get(identity)
    if not member:
        raise AuthError("Member account not found.")
    return member
    