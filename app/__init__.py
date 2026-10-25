from datetime import timedelta
from flask import Flask
from config import Config
from flask_migrate import Migrate
from .extensions import db, limiter, mail
from flask_mail import Mail
from dotenv import load_dotenv
import os
from flask_login import LoginManager
from .api import api as api
from .api_templates import api_tpl

mail = Mail()
login_manager = LoginManager()

def create_app():
    load_dotenv()
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT'))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS') == 'True'
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')
    app.config.from_object(Config)
    app.register_blueprint(api)
    app.register_blueprint(api_tpl)

    # Init extensions
    db.init_app(app)
    mail.init_app(app) 
    Migrate(app, db)
    limiter.init_app(app)

    # Session cookie hardening
    app.config.update(
        SESSION_COOKIE_NAME='bioattend_session',
        SESSION_COOKIE_HTTPONLY=True,       # JS can’t read it
        SESSION_COOKIE_SAMESITE='Lax',      # CSRF hardening
        SESSION_COOKIE_SECURE=False,        # set True only for HTTPS
        SESSION_PERMANENT=False,            # session ends with browser session by default
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),  # used when we ever set session.permanent = True
        SESSION_REFRESH_EACH_REQUEST=True,  # refresh cookie each request (limits idle hijack window)
    )

    # Flask-Login remember me cookie hardening 
    app.config.update(
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_SECURE=False,       # set True when using HTTPS
        REMEMBER_COOKIE_DURATION=timedelta(days=7),
    )

    # Flask-Login setup
    login_manager.login_view = "routes.login"   # redirect here if not logged in
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(key):
        """
        Custom user loader for Flask-Login.
        Supports namespaced IDs like 'admin:1', 'teacher:2', 'student:3'
        and gracefully falls back to numeric IDs for older sessions.
        """
        from app.models import Admin, Teacher, Student, User

        if not key:
            return None

        # New format: "role:id" used by Admin/Teacher/Student.get_id()
        if ":" in key:
            role, sid = key.split(":", 1)
            try:
                uid = int(sid)
            except ValueError:
                return None

            if role == "admin":
                return Admin.query.get(uid)
            if role == "teacher":
                return Teacher.query.get(uid)
            if role == "student":
                return Student.query.get(uid)
            return User.query.get(uid)  # optional fallback

        # Legacy numeric format for old sessions or remember_me tokens
        try:
            uid = int(key)
        except ValueError:
            return None

        # Try Teacher / Student before Admin to reduce wrong-admin matches
        teacher = Teacher.query.get(uid)
        if teacher:
            return teacher

        student = Student.query.get(uid)
        if student:
            return student

        admin = Admin.query.get(uid)
        if admin:
            return admin

        return User.query.get(uid)

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://code.jquery.com https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
        )
        return response
    
    from .routes import routes
    app.register_blueprint(routes)
    return app
