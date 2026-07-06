from flask import Blueprint, request
from app.services.auth_service import register_member, login, AuthError
from app.utils import error_response, success_response

auth_bp = Blueprint("auth", __name__)


# ── POST /api/auth/register ───────────────────────────────────────────────────

@auth_bp.post("/register")
def register():
    """
    Member self-registration.
    Body: { full_name, email, password, phone (opt), address (opt) }
    """
    body = request.get_json()

    required = ["full_name", "email", "password"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    full_name = body["full_name"].strip()
    email     = body["email"].strip()
    password  = body["password"]
    phone     = body.get("phone", "").strip() or None
    address   = body.get("address", "").strip() or None

    if len(full_name) < 2:
        return error_response("Full name must be at least 2 characters.", 400)

    if "@" not in email or "." not in email:
        return error_response("Please provide a valid email address.", 400)

    if len(password) < 8:
        return error_response("Password must be at least 8 characters.", 400)

    try:
        member = register_member(
            full_name = full_name,
            email     = email,
            password  = password,
            phone     = phone,
            address   = address,
        )
        return success_response({
            "member_code" : member.member_code,
            "full_name"   : member.full_name,
            "email"       : member.email,
            "status"      : member.status,
            "member_since": member.member_since.isoformat(),
        }, 201)

    except AuthError as e:
        return error_response(str(e), 409)  # 409 Conflict — email already exists


# ── POST /api/auth/login ──────────────────────────────────────────────────────

@auth_bp.post("/login")
def login_route():
    """
    Login for both Librarian and Member.
    Body: { email, password }
    Returns: JWT token + role + profile
    """
    body = request.get_json()

    required = ["email", "password"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    try:
        result = login(
            email    = body["email"],
            password = body["password"],
        )
        return success_response(result, 200)

    except AuthError as e:
        return error_response(str(e), 401)


# ── GET /api/auth/me ──────────────────────────────────────────────────────────

@auth_bp.get("/me")
def me():
    """
    Returns the current logged-in user's profile from their JWT token.
    Used by the frontend on page load to restore session state.
    """
    from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
    from app.services.auth_service import get_current_staff, get_current_member

    try:
        verify_jwt_in_request()
        claims   = get_jwt()
        identity = get_jwt_identity()
        role     = claims.get("role")

        if role == "librarian":
            staff = get_current_staff(identity)
            return success_response({
                "role"      : "librarian",
                "id"        : staff.id,
                "full_name" : staff.full_name,
                "email"     : staff.email,
            })

        elif role == "member":
            member = get_current_member(identity)
            return success_response({
                "role"           : "member",
                "id"             : member.id,
                "member_code"    : member.member_code,
                "full_name"      : member.full_name,
                "email"          : member.email,
                "status"         : member.status,
                "phone"          : member.phone,
                "books_borrowed" : member.books_borrowed,
                "current_fines"  : float(member.current_fines),
            })

        return error_response("Invalid token role.", 401)

    except Exception as e:
        return error_response("Invalid or expired token.", 401)


# ── PATCH /api/auth/me ─────────────────────────────────────────────────────────

@auth_bp.patch("/me")
def update_me():
    """
    Update the current logged-in user's own profile.
    Body: { full_name (opt), phone (opt) }
    - Members can update full_name and phone.
    - Librarians can update full_name only (no phone field on Staff).
    Omit a field to leave it unchanged; send phone: null to clear it.
    """
    from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity
    from app.services.auth_service import update_profile

    try:
        verify_jwt_in_request()
        claims   = get_jwt()
        identity = get_jwt_identity()
        role     = claims.get("role")
    except Exception:
        return error_response("Invalid or expired token.", 401)

    body = request.get_json(silent=True) or {}

    full_name = body.get("full_name")
    if full_name is not None:
        full_name = full_name.strip()
        if len(full_name) < 2:
            return error_response("Full name must be at least 2 characters.", 400)

    phone_provided = "phone" in body
    phone = body.get("phone")
    if phone_provided and phone is not None:
        phone = phone.strip() or None

    if full_name is None and not phone_provided:
        return error_response("Nothing to update.", 400)

    try:
        updated = update_profile(
            identity       = identity,
            role           = role,
            full_name      = full_name,
            phone          = phone,
            phone_provided = phone_provided,
        )
        return success_response(updated, 200)

    except AuthError as e:
        return error_response(str(e), 400)


@auth_bp.get("/test-email")
def test_email():
    from app.services.email_service import _send
    _send(
        subject    = "Library Email Test",
        recipients = ["smrutisawant47@gmail.com"],
        body_text  = "Email is working correctly from Central Library.",
    )
    return jsonify({"success": True, "message": "Test email sent."})