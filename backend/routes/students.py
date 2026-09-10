"""Read the authenticated account's own profile. (Kept at /api/students for
backward compatibility — the underlying owner table is still named ``students``
internally. No user-facing "Student ID" is exposed.)"""

from flask import Blueprint, jsonify
from database import execute_query
from middleware import token_required

students_bp = Blueprint('students', __name__)

_PROFILE_COLS = "id, name, email, mobile_number, created_at"


@students_bp.route('/', methods=['GET'], strict_slashes=False)
@token_required
def get_students(current_student):
    # No cross-account listing: an account may only see itself.
    account = execute_query(
        f"SELECT {_PROFILE_COLS} FROM students WHERE id = %s",
        (current_student['id'],),
        fetch_one=True,
    )
    return jsonify([account] if account else [])


@students_bp.route('/<int:student_id>', methods=['GET'])
@token_required
def get_student(current_student, student_id):
    if student_id != current_student['id']:
        return jsonify({"error": "Unauthorized"}), 403
    account = execute_query(
        f"SELECT {_PROFILE_COLS} FROM students WHERE id = %s",
        (student_id,),
        fetch_one=True,
    )
    if account is None:
        return jsonify({"error": "Account not found"}), 404
    return jsonify(account)
