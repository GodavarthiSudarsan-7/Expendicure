from flask import Blueprint, jsonify
from database import execute_query
from middleware import token_required

students_bp = Blueprint('students', __name__)


@students_bp.route('/', methods=['GET'], strict_slashes=False)
@token_required
def get_students(current_student):
    # No cross-student listing: a student may only see themselves.
    student = execute_query(
        "SELECT id, student_id, name, email, created_at FROM students WHERE id = %s",
        (current_student['id'],),
        fetch_one=True,
    )
    return jsonify([student] if student else [])


@students_bp.route('/<int:student_id>', methods=['GET'])
@token_required
def get_student(current_student, student_id):
    if student_id != current_student['id']:
        return jsonify({"error": "Unauthorized"}), 403
    student = execute_query(
        "SELECT id, student_id, name, email, created_at FROM students WHERE id = %s",
        (student_id,),
        fetch_one=True,
    )
    if student is None:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(student)
