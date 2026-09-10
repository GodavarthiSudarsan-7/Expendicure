from functools import wraps
from flask import request, jsonify
import jwt
from config import Config
from database import execute_query


def bearer_token():
    """The raw bearer token from the Authorization header, or None."""
    header = request.headers.get('Authorization', '')
    if header.startswith('Bearer '):
        return header.split(' ', 1)[1]
    return header or None


def student_from_token(token):
    """Decode ``token`` and return the student row, or None. Never raises.

    Used by endpoints that accept either a JWT or an alternative credential
    (e.g. the Phase 15 bank-SMS ingestion endpoint, which also accepts a
    per-connection ingest token).
    """
    if not token:
        return None
    try:
        data = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None
    owner_id = data.get('student_id')  # internal owner id (students.id); claim key kept for compat
    if owner_id is None:
        return None
    return execute_query(
        "SELECT id, student_id, name, email, mobile_number FROM students WHERE id = %s",
        (owner_id,),
        fetch_one=True,
    )


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check if the token is passed in the headers
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
            else:
                token = auth_header
                
        if not token:
            return jsonify({'error': 'Token is missing!'}), 401
            
        try:
            # Decode the token. The claim key stays 'student_id' for backward
            # compatibility; it carries the internal owner id (students.id).
            data = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
            owner_id = data['student_id']

            # Verify the account exists
            query = "SELECT id, student_id, name, email, mobile_number FROM students WHERE id = %s"
            current_student = execute_query(query, (owner_id,), fetch_one=True)

            if not current_student:
                return jsonify({'error': 'Account not found'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Session has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid session token'}), 401

        # Pass the current account to the route (kwarg name kept for compatibility)
        return f(current_student, *args, **kwargs)
        
    return decorated
