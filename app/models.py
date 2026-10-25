from datetime import datetime
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import Text
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import BYTEA
from sqlalchemy import UniqueConstraint

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False)

class Student(db.Model, UserMixin):
    __tablename__ = 'students'
    
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    year = db.Column(db.String(50), nullable=True) 
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)

    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def get_id(self):
        return f"student:{self.id}"

class Attendance(db.Model):
    __tablename__ = 'attendance'

    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)           #present or absent
    remarks = db.Column(db.String(255), nullable=True)
    scanned_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    source = db.Column(db.String(20), default="manual")         #manual or fingerprint

    # New fields added for Biometric Logs and R307S integration
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)   
    device_id = db.Column(db.String(50), nullable=True)          # 'R307S or R307S-01'
    finger_id = db.Column(db.Integer, nullable=True)             # template/index ID from fingerprint device
    confidence = db.Column(db.Integer, nullable=True)            # match confidence (0–100)
    role = db.Column(db.String(20), nullable=True, default='student')  # student or teacher
    department = db.Column(db.String(100), nullable=True)        # snapshot of department at log time

    # Relationships
    student = db.relationship('Student', backref=db.backref('attendance_records', lazy=True))
    teacher = db.relationship('Teacher', backref=db.backref('attendance_records', lazy=True))

    # Compatibility alias so routes can safely use Attendance.timestamp
    timestamp = db.synonym('scanned_at')

class Teacher(db.Model, UserMixin):
    __tablename__ = 'teachers'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    students = db.relationship('Student', backref='teacher', lazy=True)

    # Password helpers
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Required for Flask-Login
    def get_id(self):
        return f"teacher:{self.id}"
    
class Admin(db.Model, UserMixin):
    __tablename__ = 'admins'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"admin:{self.id}"

class BiometricTemplate(db.Model):
    __tablename__ = "biometric_templates"
    id = db.Column(db.Integer, primary_key=True)

    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    sensor_type = db.Column(db.String(32), nullable=False, default="R307")
    template_version = db.Column(db.String(32), nullable=False, default="v1")
    finger_id = db.Column(db.Integer, nullable=True)  # device slot index (optional)
    device_id = db.Column(db.String(50), nullable=True)

    # encrypted payload
    cipher_b64 = db.Column(db.Text, nullable=False)   # AES-GCM ciphertext (base64)
    nonce_b64  = db.Column(db.Text, nullable=False)   # AES-GCM nonce (base64)
    # integrity fingerprint
    tpl_sha256_hex = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)

    student = db.relationship('Student', backref=db.backref('templates', lazy=True))

    __table_args__ = (
        # prevent accidental duplicate uploads from same device slot
        UniqueConstraint('student_id', 'sensor_type', 'finger_id', name='uq_tpl_student_sensor_slot'),
    )
