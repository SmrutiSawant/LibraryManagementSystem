from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt, get_jwt_identity

def error_response(message, status_code):
    return jsonify({"success": False, "error": message}), status_code

def success_response(data, status_code=200):
    return jsonify({"success": True, "data": data}), status_code

def librarian_required():
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "librarian":
            return None, error_response("Librarian access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)

def member_required():
    try:
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get("role") != "member":
            return None, error_response("Member access required.", 403)
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)

def any_authenticated():
    try:
        verify_jwt_in_request()
        return get_jwt_identity(), None
    except Exception:
        return None, error_response("Missing or invalid token.", 401)
