from functools import wraps
from flask import abort, session, redirect, url_for, flash

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('routes.login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'teacher':
            flash("Access denied. Teachers only.", "danger")
            return redirect(url_for('routes.login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'student':
            flash("Access denied. Students only.", "danger")
            return redirect(url_for('routes.login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                return abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for('routes.admin_login'))
        return f(*args, **kwargs)
    return decorated_function
