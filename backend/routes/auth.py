from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from config import Config
from database import execute_query, run_transaction, DatabaseError, IntegrityError

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}

    required_fields = ['student_id_str', 'name', 'email', 'username', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    # Friendly pre-checks (the DB unique constraints are still the source of truth).
    existing_student = execute_query(
        "SELECT id FROM students WHERE email = %s OR student_id = %s",
        (data['email'], data['student_id_str']),
        fetch_one=True,
    )
    if existing_student:
        return jsonify({'error': 'Student with this email or ID already exists'}), 409

    existing_user = execute_query(
        "SELECT id FROM users WHERE username = %s",
        (data['username'],),
        fetch_one=True,
    )
    if existing_user:
        return jsonify({'error': 'Username already taken'}), 409

    hashed_password = generate_password_hash(data['password'])

    def _create(cursor):
        cursor.execute(
            "INSERT INTO students (student_id, name, email) VALUES (%s, %s, %s)",
            (data['student_id_str'], data['name'], data['email']),
        )
        new_student_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO users (student_id, username, password_hash) VALUES (%s, %s, %s)",
            (new_student_id, data['username'], hashed_password),
        )
        return new_student_id

    try:
        run_transaction(_create)
    except IntegrityError:
        # Unique constraint hit between the pre-check and the insert.
        return jsonify({'error': 'Student or username already exists'}), 409
    except DatabaseError as e:
        print(f"Registration error: {e}")
        return jsonify({'error': 'An error occurred during registration'}), 500
    except Exception as e:  # pragma: no cover - unexpected driver errors
        print(f"Registration error: {e}")
        return jsonify({'error': 'An error occurred during registration'}), 500

    return jsonify({'message': 'Registration successful'}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}

    if not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password are required'}), 400

    user = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (data['username'],),
        fetch_one=True,
    )

    if not user:
        return jsonify({'error': 'Invalid username or password'}), 401

    if check_password_hash(user['password_hash'], data['password']):
        token = jwt.encode({
            'student_id': user['student_id'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
        }, Config.SECRET_KEY, algorithm="HS256")

        student = execute_query(
            "SELECT id, student_id, name, email FROM students WHERE id = %s",
            (user['student_id'],),
            fetch_one=True,
        )

        return jsonify({'token': token, 'student': student}), 200

    return jsonify({'error': 'Invalid username or password'}), 401
