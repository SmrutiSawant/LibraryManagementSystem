from flask import Blueprint, request, jsonify
from app.services.auth_service import register_member, login, AuthError

auth_bp = Blueprint("auth", __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code


def success_response(data, status_code=200):
    return jsonify({"success": True, "data": data}), status_code


# ── POST /api/auth/register ───────────────────────────────────────────────────

@auth_bp.post("/register")
def register():
    """
    Member self-registration.
    Body: { full_name, email, password, phone (opt), address (opt) }
    """
    body = request.get_json()

    # ── Required field validation ─────────────────────────────────────────────
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

    # ── Basic field checks ────────────────────────────────────────────────────
    if len(full_name) < 2:
        return error_response("Full name must be at least 2 characters.", 400)

    if "@" not in email or "." not in email:
        return error_response("Please provide a valid email address.", 400)

    if len(password) < 8:
        return error_response("Password must be at least 8 characters.", 400)

    # ── Call service ──────────────────────────────────────────────────────────
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

    # ── Required field validation ─────────────────────────────────────────────
    required = ["email", "password"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return error_response(
            f"Missing required fields: {', '.join(missing)}", 400
        )

    # ── Call service ──────────────────────────────────────────────────────────
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
                "role"         : "member",
                "id"           : member.id,
                "member_code"  : member.member_code,
                "full_name"    : member.full_name,
                "email"        : member.email,
                "status"       : member.status,
                "books_borrowed" : member.books_borrowed,
                "current_fines"  : float(member.current_fines),
            })

        return error_response("Invalid token role.", 401)

    except Exception as e:
        return error_response("Invalid or expired token.", 401)

@auth_bp.get("/test-email")
def test_email():
    from app.services.email_service import _send
    _send(
        subject    = "Library Email Test",
        recipients = ["smrutisawant47@gmail.com"],
        body_text  = "Email is working correctly from Central Library.",
    )
    return jsonify({"success": True, "message": "Test email sent."})

