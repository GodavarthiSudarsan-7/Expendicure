import re
import secrets

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from config import Config
from database import execute_query, run_transaction, DatabaseError, IntegrityError

auth_bp = Blueprint('auth', __name__)

# Digits only after stripping spaces / dashes / parens / leading "+".
# E.164 allows up to 15 digits; not hard-coded to any one country.
_MOBILE_CLEAN = re.compile(r"[\s\-().]")
_MOBILE_OK = re.compile(r"^\+?[0-9]{8,15}$")


def _normalize_mobile(raw):
    """Return (normalized, None) or (None, error). '+91 98765 43210' ->
    '+919876543210'; '9876543210' -> '9876543210'."""
    if not raw or not isinstance(raw, str):
        return None, "mobile_number is required"
    cleaned = _MOBILE_CLEAN.sub("", raw.strip())
    if not _MOBILE_OK.match(cleaned):
        return None, "Enter a valid mobile number (8–15 digits, optional leading +)."
    return cleaned, None


def _account_reference():
    """An opaque internal account reference for the (NOT NULL, UNIQUE)
    ``students.student_id`` column. Never shown to users."""
    return "U" + secrets.token_hex(5).upper()


@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}

    required_fields = ['name', 'mobile_number', 'username', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400

    mobile, err = _normalize_mobile(data.get('mobile_number'))
    if err:
        return jsonify({'error': err}), 400

    email = (data.get('email') or '').strip() or None

    # Friendly pre-checks (the DB unique constraints are still the source of truth).
    clauses, params = ["mobile_number = %s"], [mobile]
    if email:
        clauses.append("email = %s")
        params.append(email)
    existing = execute_query(
        f"SELECT id FROM students WHERE {' OR '.join(clauses)}",
        tuple(params),
        fetch_one=True,
    )
    if existing:
        return jsonify({'error': 'An account with this mobile number or email already exists'}), 409

    existing_user = execute_query(
        "SELECT id FROM users WHERE username = %s",
        (data['username'],),
        fetch_one=True,
    )
    if existing_user:
        return jsonify({'error': 'Username already taken'}), 409

    hashed_password = generate_password_hash(data['password'])
    account_ref = _account_reference()

    def _create(cursor):
        cursor.execute(
            "INSERT INTO students (student_id, name, email, mobile_number) VALUES (%s, %s, %s, %s)",
            (account_ref, data['name'], email, mobile),
        )
        new_owner_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO users (student_id, username, password_hash) VALUES (%s, %s, %s)",
            (new_owner_id, data['username'], hashed_password),
        )
        return new_owner_id

    try:
        run_transaction(_create)
    except IntegrityError:
        # Unique constraint hit between the pre-check and the insert.
        return jsonify({'error': 'That account or username already exists'}), 409
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

    user_row = execute_query(
        "SELECT * FROM users WHERE username = %s",
        (data['username'],),
        fetch_one=True,
    )

    if not user_row:
        return jsonify({'error': 'Invalid username or password'}), 401

    if check_password_hash(user_row['password_hash'], data['password']):
        # The JWT claim key stays 'student_id' for backward compatibility with
        # already-issued tokens and the middleware; it carries the internal
        # owner id (students.id), never a user-facing value.
        token = jwt.encode({
            'student_id': user_row['student_id'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(days=1)
        }, Config.SECRET_KEY, algorithm="HS256")

        account = execute_query(
            "SELECT id, name, email, mobile_number FROM students WHERE id = %s",
            (user_row['student_id'],),
            fetch_one=True,
        )

        return jsonify({'token': token, 'user': account}), 200

    return jsonify({'error': 'Invalid username or password'}), 401
