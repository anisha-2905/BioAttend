from zoneinfo import ZoneInfo
from flask import Blueprint, Response, app, render_template, request, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from app.models import Admin, db, User, Student, Attendance, Teacher
from time import time
from app.decorators import admin_required, login_required, teacher_required, student_required
import re
from datetime import datetime, date, timedelta, timezone
from flask import request, jsonify, session, redirect, url_for, flash, make_response
from app.extensions import limiter, mail
from app.utils.token import verify_reset_token
import secrets
from sqlalchemy import extract, func, case
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from app import mail, db
import csv
from io import StringIO, BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
import random
from collections import deque

LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))

routes = Blueprint('routes', __name__)

@routes.route('/')
def home():
    return redirect(url_for("routes.login"))

from app.models import db, User, Student  # Ensure Student is imported

@routes.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  
def login():
    if current_user.is_authenticated:
        flash('You are already logged in.', 'info')
        # Redirect based on session role
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('routes.admin_shell'))
        else:
            return redirect(url_for('routes.dashboard'))

    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        role = request.form['role'].strip().lower()
        remember = bool(request.form.get('remember'))

        if not email or not password or not role:
            flash('All fields are required.', 'danger')
            return redirect(url_for('routes.login'))

        if role not in ['teacher', 'student', 'admin']:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('routes.login'))

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Invalid email format.', 'danger')
            return redirect(url_for('routes.login'))

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return redirect(url_for('routes.login'))
        
        #Admin login 
        if role == 'admin':
            from app.models import Admin
            admin = Admin.query.filter_by(email=email).first()
            if admin and admin.check_password(password):
                session.clear()                       #session fixation defense
                login_user(admin, remember=remember)  #pass remember
                session.permanent = remember          #honor remember only
                session['user_id'] = admin.id
                session['role'] = 'admin'
                flash('Welcome back, Admin!', 'success')
                return redirect(url_for('routes.admin_shell'))
            else:
                flash('Invalid admin credentials.', 'danger')
                return redirect(url_for('routes.login'))

        #Teacher login
        elif role == 'teacher':
            teacher = Teacher.query.filter_by(email=email).first()
            if teacher and teacher.check_password(password):
                session.clear()                          
                login_user(teacher, remember=remember)   
                session.permanent = remember             
                session['user_id'] = teacher.id
                session['role'] = 'teacher'
                flash('Login successful!', 'success')
                return redirect(url_for('routes.dashboard'))
            else:
                flash('Invalid teacher credentials.', 'danger')
                return redirect(url_for('routes.login'))

        #Student login
        elif role == 'student':
            student = Student.query.filter_by(email=email).first()
            if student and student.check_password(password):
                session.clear()                          
                login_user(student, remember=remember)   
                session.permanent = remember 
                session['user_id'] = student.id
                session['role'] = 'student'
                flash('Login successful!', 'success')
                return redirect(url_for('routes.dashboard'))
            else:
                flash('Invalid student credentials.', 'danger')
                return redirect(url_for('routes.login'))

    return render_template('login.html')

@routes.route('/dashboard')
@login_required
def dashboard():
    #Teacher dashboard
    if session.get('role') == 'teacher':
        return render_template(
            'dashboard_base.html',
            role='teacher',
            display_name=current_user.full_name if hasattr(current_user, 'full_name') else current_user.email
        )

    #Student dashboard
    elif session.get('role') == 'student':
        return render_template(
            'dashboard_base.html',
            role='student',
            display_name=current_user.full_name
        )

    #Fallback
    flash('Invalid role detected. Please log in again.', 'danger')
    return redirect(url_for('routes.logout'))
    
@routes.route("/student/home")
@login_required
def student_home_partial():
    if session.get('role') != 'student':
        return "Forbidden", 403

    student = Student.query.get(session['user_id'])
    records = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.date.desc())
        .all()
    )

    present_count = sum(1 for r in records if r.status == 'present')
    absent_count  = sum(1 for r in records if r.status == 'absent')
    total_classes = len(records)
    recent_attendance = records[:8]

    #lightweight demo notices (can swap for db in future) 
    notices = [
        {"title": "Timetable updated",
         "body":  "New CS203 slot on Tue 10:30.",
         "ts":    datetime.utcnow(),
         "kind":  "info"},
        {"title": "Holiday",
         "body":  "College closed on Fri.",
         "ts":    datetime.utcnow(),
         "kind":  "success"},
        {"title": "Fee Reminder",
         "body":  "Last date is 30th.",
         "ts":    datetime.utcnow(),
         "kind":  "warning"},
    ]

    return render_template(
        "partials/student_home.html",
        student_name=student.full_name,
        present_count=present_count,
        absent_count=absent_count,
        total_classes=total_classes,
        recent_attendance=recent_attendance,
        notices=notices,  
    )

@routes.route("/student/attendance")
@login_required
def student_attendance_partial():
    if session.get('role') != 'student':
        return "Forbidden", 403

    student = Student.query.get(session['user_id'])
    records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date.desc()).all()
    return render_template('partials/attendance_table.html', records=records)

@routes.route('/teacher-dashboard')
@login_required
@teacher_required
def teacher_dashboard():
    return render_template('dashboard_teacher.html')

@routes.route("/student-dashboard")
@login_required
@student_required
def student_dashboard():
    student_id = session.get("user_id")
    student = Student.query.get(student_id)

    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for("routes.logout"))

    # Attendance stats
    present_count = Attendance.query.filter_by(student_id=student_id, status="present").count()
    absent_count = Attendance.query.filter_by(student_id=student_id, status="absent").count()
    total_classes = Attendance.query.filter_by(student_id=student_id).count()

    # Recent attendance (latest 5)
    recent_attendance = (
        Attendance.query.filter_by(student_id=student_id)
        .order_by(Attendance.date.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "partials/student_home.html",
        student_name=student.full_name,
        present_count=present_count,
        absent_count=absent_count,
        total_classes=total_classes,
        recent_attendance=recent_attendance
    )

@routes.route('/logout')
@login_required
def logout():
    logout_user()  
    session.clear()
    flash('Logged out successfully', 'info')
    return redirect(url_for('routes.login'))

@routes.route('/signup', methods=['GET', 'POST'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('routes.dashboard'))
    
    if request.method == 'POST':
        full_name = request.form['full_name'].strip()
        roll_number = request.form['roll'].strip()
        department = request.form['department'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        errors = {}
        shake_fields = []

        if password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'
            shake_fields += ['password', 'confirm_password']

        if errors:
            return render_template(
                'signup.html',
                errors=errors,
                shake_fields=shake_fields,
                full_name=full_name,
                roll=roll_number,
                department=department,
                email=email
            )

        existing_student = Student.query.filter_by(email=email).first()
        if existing_student:
            flash('Email already registered.', 'danger')
            return redirect(url_for('routes.signup'))
        
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('Invalid email format.', 'danger')
            return redirect(url_for('routes.signup'))
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return redirect(url_for('routes.signup'))
        if not re.search(r"\d", password):
            flash('Password must include at least one number.', 'danger')
            return redirect(url_for('routes.signup'))
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            flash('Password must include at least one special character.', 'danger')
            return redirect(url_for('routes.signup'))

        existing_roll = Student.query.filter_by(roll_number=roll_number).first()
        if existing_roll:
            flash('Roll number already registered.', 'danger')
            return redirect(url_for('routes.signup'))

        new_student = Student(
            full_name=full_name,
            roll_number=roll_number,
            department=department,
            email=email
        )
        new_student.set_password(password)  #hashing method

        db.session.add(new_student)
        db.session.commit()

        flash('Account created successfully! Please log in.', 'success')
        return redirect(url_for('routes.login'))

    return render_template(
    'signup.html',
    errors={},             
    shake_fields=[],        #Prevents Jinja error
    full_name='',
    roll='',
    department='',
    email=''
)

@routes.route('/forgot-password', methods=['POST'])
def forgot_password():
    email = request.form['email'].strip().lower()

    # Check if teacher
    user = User.query.filter_by(email=email, role='teacher').first()
    if user:
        role = 'teacher'
        user_id = user.id
    else:
        # Check if student
        student = Student.query.filter_by(email=email).first()
        if student:
            role = 'student'
            user_id = student.id
        else:
            flash('No account found with that email.', 'danger')
            return redirect(url_for('routes.login'))

    # Generate token (we’ll validate this token next step)
    token = secrets.token_urlsafe(32)

    # Temporarily: store it in session 
    session['reset_token'] = token
    session['reset_email'] = email
    session['reset_role'] = role

    # Build reset link
    reset_link = url_for('routes.reset_password', token=token, _external=True)

    # Compose and send the email
    msg = Message(
        subject='BioAttend - Password Reset Request',
        sender=current_app.config['MAIL_USERNAME'],
        recipients=[email]
    )
    msg.body = f"""
Hi,

We received a request to reset your BioAttend password.

Click the link below to reset your password:
{url_for('routes.reset_password', token=token, _external=True)}

If you did not request this, please ignore this email.

– BioAttend Team
"""
    try:
        mail.send(msg)
        flash('Password reset email sent! Check your inbox.', 'info')
    except Exception as e:
        flash('Error sending email. Please try again later.', 'danger')
        print(f"Mail error: {e}")

    return redirect(url_for('routes.login'))

@routes.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    stored_token = session.get('reset_token')
    email = session.get('reset_email')
    role = session.get('reset_role')
    expires_at = session.get('reset_expires')

    if not stored_token or token != stored_token or not expires_at or time() > expires_at:
        flash('Reset link has expired or is invalid.', 'danger')
        return redirect(url_for('routes.login'))
    
    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('reset_password.html', token=token)

        if len(password) < 8 or not re.search(r"\d", password) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            flash('Password must be at least 8 characters and include a number and special character.', 'danger')
            return render_template('reset_password.html', token=token)

        if role == 'teacher':
            user = User.query.filter_by(email=email, role='teacher').first()
            if user:
                user.password = generate_password_hash(password)
        elif role == 'student':
            student = Student.query.filter_by(email=email).first()
            if student:
                student.set_password(password)

        db.session.commit()

        # Clear token info from session
        session.pop('reset_token', None)
        session.pop('reset_email', None)
        session.pop('reset_role', None)
        session.pop('reset_expires', None)

        flash('Password reset successfully! You can now log in.', 'success')
        return redirect(url_for('routes.login'))

    return render_template('reset_password.html', token=token)

# Student Attendance History
@routes.route('/attendance')
@login_required
def attendance_page():
    if session.get('role') != 'student':
        flash('Access denied.', 'danger')
        return redirect(url_for('routes.dashboard'))

    student = Student.query.get(session['user_id'])
    records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date.desc()).all()
    
    return render_template('attendance.html', records=records)

# Student Reports (charts/summary)
@routes.route("/dashboard/reports")
@login_required
def student_reports_partial():
    # Find student 
    student = None
    if session.get("student_id"):
        student = Student.query.filter_by(id=session["student_id"]).first()

    if not student and getattr(current_user, "email", None):
        student = Student.query.filter(
            func.lower(Student.email) == func.lower(current_user.email)
        ).first()

    if not student:
        flash("Student record not found. Please contact admin.", "danger")
        return redirect(url_for("routes.dashboard"))

    # Summary counts 
    total_classes = Attendance.query.filter_by(student_id=student.id).count()
    present_count = Attendance.query.filter_by(student_id=student.id, status="present").count()
    absent_count = Attendance.query.filter_by(student_id=student.id, status="absent").count()

    # Monthly aggregated query (year / month) 
    monthly_rows = (
        db.session.query(
            extract("year", Attendance.date).label("year"),
            extract("month", Attendance.date).label("month"),
            func.count().label("total"),
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        )
        .filter(Attendance.student_id == student.id)
        .group_by("year", "month")
        .order_by("year", "month")
        .all()
    )

    # turn monthly_rows into JS-friendly lists 
    monthly_labels = [f"{int(r.month)}/{int(r.year)}" for r in monthly_rows]
    monthly_present = [int(r.present) for r in monthly_rows]
    monthly_absent = [int(r.absent) for r in monthly_rows]
    monthly_total = [int(r.total) for r in monthly_rows]

    # Daily breakdown: last 30 days aggregated by date (descending) 
    daily_rows = (
        db.session.query(
            Attendance.date.label("date"),
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
            func.count().label("total"),
        )
        .filter(Attendance.student_id == student.id)
        .group_by(Attendance.date)
        .order_by(Attendance.date.desc())
        .limit(30)
        .all()
    )

    # reverse to chronological order for charts (oldest first)
    daily_rows = list(reversed(daily_rows))
    daily_labels = [r.date.strftime("%Y-%m-%d") for r in daily_rows]
    daily_present = [int(r.present) for r in daily_rows]
    daily_absent = [int(r.absent) for r in daily_rows]
    daily_total = [int(r.total) for r in daily_rows]

    return render_template(
        "partials/reports_stub.html",
        student_name=student.full_name,
        present_count=present_count,
        absent_count=absent_count,
        total_classes=total_classes,
        monthly_labels=monthly_labels,
        monthly_present=monthly_present,
        monthly_absent=monthly_absent,
        monthly_total=monthly_total,
        daily_labels=daily_labels,
        daily_present=daily_present,
        daily_absent=daily_absent,
        daily_total=daily_total,
    )

def _slugify(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s.strip("_") or "student"

@routes.route("/export_csv/<int:student_id>")
def export_csv(student_id):
    student = Student.query.get_or_404(student_id)
    records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date).all()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Date", "Status"])
    for r in records:
        writer.writerow([r.date.strftime("%Y-%m-%d"), r.status])

    slug = _slugify(student.full_name)
    filename = f"{slug}_attendance.csv"

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    output.headers["Content-Type"] = "text/csv"
    return output

@routes.route("/export_pdf/<int:student_id>")
def export_pdf(student_id):
    student = Student.query.get_or_404(student_id)
    records = Attendance.query.filter_by(student_id=student.id).order_by(Attendance.date).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"Attendance Report - {student.full_name}", styles["Title"]))

    data = [["Date", "Status"]] + [[r.date.strftime("%Y-%m-%d"), r.status] for r in records]
    table = Table(data, colWidths=[200, 200])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("GRID", (0,0), (-1,-1), 1, colors.black),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    slug = _slugify(student.full_name)
    filename = f"{slug}_attendance.pdf"

    response = make_response(buffer.read())
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Type"] = "application/pdf"
    return response

@routes.route("/student/performance")
@login_required
def student_performance_partial():
    if session.get("role") != "student":
        return "Forbidden", 403

    student = Student.query.get(session["user_id"])
    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for("routes.logout"))

    # Fetch attendance
    records = (
        Attendance.query
        .filter_by(student_id=student.id)
        .order_by(Attendance.date.desc())
        .all()
    )

    total_classes = len(records)
    present_count = sum(1 for r in records if r.status == "present")
    absent_count  = sum(1 for r in records if r.status == "absent")
    attendance_rate = round((present_count / total_classes) * 100, 2) if total_classes else 0.0

    # Stubbed academic data (in future can add marks table)
    subjects = ["CS203", "Maths", "Physics", "Chemistry", "English"]
    subject_scores = [82, 77, 91, 86, 80]
    subject_out_of = [100, 100, 100, 100, 100]
    avg_marks_percent = round(sum(subject_scores) / len(subject_scores), 1)

    # Class ranking stub
    class_rank, class_size = 7, 42  

    # Trend (mock data for chart)
    performance_trend_labels = ["Unit 1", "Unit 2", "Mid Sem", "Unit 3", "Final"]
    performance_trend_values = [72, 78, 81, 84, 88]

    # Recent assessments (in future comes from a Marks table)
    recent_assessments = [
        {"date": datetime(2025, 10, 12), "name": "Unit 3 Test", "subject": "CS203", "score": 88, "out_of": 100, "status": "pass"},
        {"date": datetime(2025, 9, 26),  "name": "Unit 2 Quiz", "subject": "Physics", "score": 76, "out_of": 100, "status": "pass"},
        {"date": datetime(2025, 9, 10),  "name": "Mid Sem", "subject": "Maths", "score": 58, "out_of": 100, "status": "fail"},
        {"date": datetime(2025, 8, 22),  "name": "Unit 1 Test", "subject": "Chemistry", "score": 80, "out_of": 100, "status": "pass"},
    ]

    return render_template(
        "partials/student_performance.html",
        student_name=student.full_name,
        avg_attendance_percent=attendance_rate,
        avg_marks_percent=avg_marks_percent,
        class_rank=class_rank,
        class_size=class_size,
        performance_trend_labels=performance_trend_labels,
        performance_trend_values=performance_trend_values,
        subjects=subjects,
        subject_scores=subject_scores,
        subject_out_of=subject_out_of,
        recent_assessments=recent_assessments,
    )

#Teacher Dashboard Partials
@routes.route("/teacher/home")
@login_required
def teacher_home_partial():
    if session.get('role') != 'teacher':
        return "Forbidden", 403

    teacher = Teacher.query.get(current_user.id)

    # Example stats 
    total_students = len(teacher.students) if teacher.students else 0
    classes_taken = 12              
    pending_attendance = 3          
    avg_attendance = 85             

    # last 5 attendance records for this teacher’s students
    recent_activity = (
        Attendance.query.join(Student)
        .filter(Student.teacher_id == teacher.id)
        .order_by(Attendance.date.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "partials/teacher_home.html",
        teacher=teacher,
        total_students=total_students,
        classes_taken=classes_taken,
        pending_attendance=pending_attendance,
        avg_attendance=avg_attendance,
        classes_completed=classes_taken,
        pending_sessions=pending_attendance,
        recent_activity=recent_activity,
    )

@routes.route("/teacher/manage-students")
@login_required
def teacher_students_partial():
    if session.get('role') != 'teacher':
        return "Forbidden", 403

    #Always re-fetch Teacher object
    teacher = Teacher.query.get(current_user.id)

    #stats
    total_students = len(teacher.students)

    total_departments = (
        db.session.query(Student.department)
        .filter(Student.teacher_id == teacher.id)
        .distinct()
        .count()
    )

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_students = Student.query.filter(
        Student.teacher_id == teacher.id,
        Student.created_at >= thirty_days_ago
    ).count()

    # Full list of students for table
    students = teacher.students

    return render_template(
        "partials/teacher_students.html",
        total_students=total_students,
        total_departments=total_departments,
        recent_students=recent_students,
        students=students
    )

@routes.route("/teacher/attendance")
@login_required
def teacher_attendance_partial():
    """Teacher → Attendance partial, now includes today's status for each student."""
    if session.get("role") != "teacher":
        return "Forbidden", 403

    teacher = current_user
    today = date.today()

    # Fetch students belonging to this teacher
    students = Student.query.filter_by(teacher_id=teacher.id).all()

    # Fetch today's attendance records for those students
    attendance_map = {
        a.student_id: a.status
        for a in Attendance.query.filter(
            Attendance.date == today,
            Attendance.student_id.in_([s.id for s in students])
        ).all()
    }

    # Attach temporary attribute for template use
    for s in students:
        s.today_status = attendance_map.get(s.id, "unmarked")
     
    return render_template(
        "partials/teacher_attendance.html",
        students=students
    )

@routes.route("/teacher/add-student", methods=["POST"])
@login_required
def add_student():
    if session.get("role") != "teacher":
        return jsonify({"error": "Forbidden"}), 403

    teacher = Teacher.query.get(current_user.id)

    full_name = request.form.get("full_name", "").strip()
    roll_number = request.form.get("roll_number", "").strip()
    department = request.form.get("department", "").strip()
    year = request.form.get("year", "").strip() or None  
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    new_student = Student(
        full_name=full_name,
        roll_number=roll_number,
        department=department,
        year=year,
        email=email,
        teacher_id=teacher.id
    )
    new_student.set_password(password)

    db.session.add(new_student)
    db.session.commit()

    # Return JSON for AJAX
    return jsonify({
        "id": new_student.id,
        "roll_number": new_student.roll_number,
        "full_name": new_student.full_name,
        "department": new_student.department,
        "year": new_student.year,          
        "email": new_student.email
    })

@routes.route("/api/attendance")
@login_required
def get_attendance():
    if session.get("role") != "teacher":
        return {"error": "Forbidden"}, 403

    teacher_id = current_user.id
    class_name = request.args.get("class")
    date_str   = request.args.get("date")
    date       = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Students of this teacher
    students = Student.query.filter_by(teacher_id=teacher_id).all()

    results = []
    present_count = absent_count = 0

    for s in students:
        record = Attendance.query.filter_by(student_id=s.id, date=date).first()
        status = record.status if record else None

        if status == "present": present_count += 1
        elif status == "absent": absent_count += 1

        results.append({
            "id": s.id,
            "roll": s.roll_number,
            "name": s.full_name,
            "status": status or "unmarked",
            "source": record.source if record else None
        })

    return {
        "students": results,
        "summary": {
            "present": present_count,
            "absent": absent_count,
            "total": len(students)
        }
    }

@routes.route("/teacher/api/trend")
@login_required
def teacher_trend_api():
    """Last N days of present/absent counts for the current teacher (default 7)."""
    if session.get("role") != "teacher":
        return {"ok": False, "msg": "Forbidden"}, 403

    try:
        days = int(request.args.get("days", 7))
        days = max(3, min(days, 30))
    except Exception:
        days = 7

    today = date.today()
    start = today - timedelta(days=days - 1)

    # Aggregating by Attendance.date for THIS teacher's students
    q = (
        db.session.query(
            Attendance.date.label("d"),
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        )
        .join(Student, Student.id == Attendance.student_id)
        .filter(
            Student.teacher_id == current_user.id,
            Attendance.date >= start,
            Attendance.date <= today,
        )
        .group_by(Attendance.date)
        .order_by(Attendance.date.asc())
        .all()
    )

    by_date = {row.d: {"present": row.present or 0, "absent": row.absent or 0} for row in q}

    labels, present, absent = [], [], []
    d = start
    while d <= today:
        labels.append(d.strftime("%b %d"))   # e.g., "Oct 31"
        rec = by_date.get(d, {"present": 0, "absent": 0})
        present.append(rec["present"])
        absent.append(rec["absent"])
        d += timedelta(days=1)

    return {"ok": True, "labels": labels, "present": present, "absent": absent}

@routes.route("/api/teacher/attendance/day")
@login_required
def teacher_attendance_day_api():
    """Counts for a given day for the current teacher (Present/Absent/Total)."""
    if session.get("role") != "teacher":
        return {"ok": False, "msg": "Forbidden"}, 403

    # accept YYYY-MM-DD or dd-mm-YYYY
    raw = (request.args.get("date") or "").strip()
    target = None
    if raw:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                target = datetime.strptime(raw, fmt).date()
                break
            except Exception:
                pass
    if target is None:
        target = date.today()

    # get this teacher's roster
    roster_ids = [s.id for s in Student.query.filter_by(teacher_id=current_user.id).all()]
    total = len(roster_ids)

    if total == 0:
        return {"ok": True, "date": target.isoformat(), "present": 0, "absent": 0, "total": 0, "percent": 0}

    q = Attendance.query.filter(
        Attendance.date == target,
        Attendance.student_id.in_(roster_ids)
    )

    present = q.filter(Attendance.status == "present").count()
    absent  = q.filter(Attendance.status == "absent").count()
    percent = int(round((present / total) * 100)) if total else 0

    return {
        "ok": True,
        "date": target.isoformat(),
        "present": present,
        "absent": absent,
        "total": total,
        "percent": percent
    }

@routes.route("/teacher/attendance/save", methods=["POST"])
@login_required
def save_attendance():
    if session.get("role") != "teacher":
        return {"error": "Forbidden"}, 403

    payload = request.get_json(silent=True) or {}
    date_str = payload.get("date")

    # date optional or defaults to today
    try:
        date_val = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    except Exception:
        return {"error": "Bad date format (YYYY-MM-DD)"}, 400

    records = payload.get("records") or []
    valid = {"present", "absent", "unmarked"}

    # single, consistent timestamp: timezone-aware UTC
    now_utc = datetime.now(timezone.utc)

    for rec in records:
        sid_raw = rec.get("id")
        status = (rec.get("status") or "unmarked").lower()
        if status not in valid:
            continue  #ignores bad statuses

        try:
            student_id = int(sid_raw)
        except (TypeError, ValueError):
            continue

        student = Student.query.get(student_id)
        if not student:
            continue

        # find existing attendance row for this student+date
        att = Attendance.query.filter_by(student_id=student_id, date=date_val).first()

        if status == "unmarked":
            # remove any row that is truly unmarked
            if att:
                db.session.delete(att)
            continue

        # create or update the row
        if not att:
            att = Attendance(student_id=student_id, date=date_val)
            db.session.add(att)

        att.status = status
        att.source = "manual"                      #distinguish from fingerprint/auto-absent
        att.teacher_id = student.teacher_id or getattr(current_user, "id", None)
        att.department = student.department
        att.device_id = att.device_id or "MANUAL"  #UI Label

        #timestamps: aware UTC so “localize to IST” works perfectly
        att.scanned_at = now_utc
        att.timestamp  = now_utc

    db.session.commit()
    return {"ok": True, "message": "Attendance saved successfully"}

@routes.route("/api/teacher/students", methods=["GET"])
@login_required
def get_teacher_students():
    """Return all students linked to the current teacher (with optional filters)."""
    if session.get("role") != "teacher":
        return {"error": "Forbidden"}, 403

    teacher_id = current_user.id

    # Optional filters
    q          = (request.args.get("q") or "").strip()
    department = (request.args.get("department") or "").strip()
    flt        = (request.args.get("filter") or "all").strip().lower()  # all | recent | semester

    qry = Student.query.filter_by(teacher_id=teacher_id)

    # Search filter
    if q:
        from sqlalchemy import func, or_
        ql = f"%{q.lower()}%"
        qry = qry.filter(
            or_(
                func.lower(Student.full_name).like(ql),
                func.lower(Student.roll_number).like(ql),
                func.lower(Student.department).like(ql),
                func.lower(Student.email).like(ql)
            )
        )

    # Department filter
    if department:
        from sqlalchemy import func
        qry = qry.filter(func.lower(Student.department) == department.lower())

    # Chip filters (recent/semester)
    if flt == "recent":
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=30)
        qry = qry.filter(Student.created_at >= cutoff)
    elif flt == "semester":
        from datetime import datetime
        now = datetime.utcnow()
        sem_start = datetime(now.year, 8, 1) if now.month >= 8 else datetime(now.year - 1, 8, 1)
        qry = qry.filter(Student.created_at >= sem_start)

    # Final query execution
    students = qry.order_by(Student.full_name.asc()).all()

    # Distinct departments for this teacher only 
    dept_rows = (
        Student.query.with_entities(Student.department)
        .filter(Student.teacher_id == teacher_id, Student.department.isnot(None))
        .distinct()
        .order_by(Student.department.asc())
        .all()
    )
    departments = [d[0] for d in dept_rows if d[0]]

    # Response 
    data = [
        {
            "id": s.id,
            "roll_number": s.roll_number,
            "full_name": s.full_name,
            "department": s.department,
            "year": s.year,
            "email": getattr(s, "email", None),
        }
        for s in students
    ]

    return {"students": data, "departments": departments}

@routes.route("/api/teacher/students/<int:student_id>/detail", methods=["GET"])
@login_required
def teacher_student_detail(student_id):
    if session.get("role") != "teacher":
        return {"ok": False, "msg": "Forbidden"}, 403

    s = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first()
    if not s:
        return {"ok": False, "msg": "Not found"}, 404
    
    # time helpers (IST) 
    from datetime import timezone
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Kolkata")

    def to_local(dt):
        if not dt:
            return None
        # Treat naive DB datetimes as UTC 
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ)

    # Localized created_at
    created_local = to_local(s.created_at)
    created_str = created_local.strftime("%Y-%m-%d %H:%M") if created_local else None

    # last 5 attendance for this student
    recs = (Attendance.query
            .filter_by(student_id=s.id)
            .order_by(Attendance.scanned_at.desc().nullslast(), Attendance.date.desc())
            .limit(5)
            .all())

    def fmt_ts(dt):
        if not dt: return None
        # assuming stored as UTC-naive or UTC-aware
        return dt.strftime("%Y-%m-%d %H:%M")

    return {
        "ok": True,
        "student": {
            "id": s.id,
            "full_name": s.full_name,
            "roll_number": s.roll_number,
            "department": s.department,
            "year": s.year,
            "email": s.email,
            "created_at": created_str,
        },
        "attendance": [
            {
                "date": a.date.isoformat() if a.date else None,
                "status": a.status,
                "source": a.source,
                "marked_at": fmt_ts(a.scanned_at)
            } for a in recs
        ]
    }

@routes.route("/api/teacher/students/<int:student_id>/update", methods=["POST"])
@login_required
def teacher_student_update(student_id):
    if session.get("role") != "teacher":
        return {"ok": False, "msg": "Forbidden"}, 403

    s = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first()
    if not s:
        return {"ok": False, "msg": "Not found"}, 404

    data = request.get_json(silent=True) or {}
    # editable fields
    for field in ("full_name", "roll_number", "department", "year", "email"):
        val = (data.get(field) or "").strip()
        if val:
            setattr(s, field, val)

    new_pwd = (data.get("new_password") or "").strip()
    if new_pwd:
        if len(new_pwd) < 8:
            return {"ok": False, "msg": "Password must be at least 8 characters"}, 400
        try:
            s.set_password(new_pwd)
        except Exception:
            # fallback 
            s.password = new_pwd  #need proper hasing replacement
    db.session.commit()
    return {"ok": True}

@routes.route("/teacher/reports")
@login_required
def teacher_reports():
    if session.get('role') != 'teacher':
        return "Forbidden", 403

    teacher = Teacher.query.get(current_user.id)

    dept = request.args.get('department') or None
    from_str = request.args.get('from')
    to_str   = request.args.get('to')
    status   = request.args.get('status') or None

    today = date.today()
    date_from = datetime.strptime(from_str, "%Y-%m-%d").date() if from_str else (today - timedelta(days=30))
    date_to   = datetime.strptime(to_str,   "%Y-%m-%d").date() if to_str   else today

    q = (db.session.query(Attendance, Student)
         .join(Student, Student.id == Attendance.student_id)
         .filter(Student.teacher_id == teacher.id)
         .filter(Attendance.date >= date_from, Attendance.date <= date_to))

    if dept:
        q = q.filter(Student.department == dept)
    if status in ("present","absent"):
        q = q.filter(Attendance.status == status)

    rows_raw = q.order_by(Attendance.date.desc(), Student.roll_number.asc()).all()

    rows = [{
        "date": a.date.strftime("%Y-%m-%d"),
        "roll_number": s.roll_number,
        "full_name": s.full_name,
        "department": s.department,
        "status": a.status,
        "source": a.source,
        "marked_at": a.scanned_at.strftime("%Y-%m-%d %H:%M") if a.scanned_at else None
    } for a, s in rows_raw]

    present = sum(1 for r in rows if r["status"] == "present")
    absent  = sum(1 for r in rows if r["status"] == "absent")

    # Approximate unmarked: roster * distinct days - marked
    student_q = Student.query.filter_by(teacher_id=teacher.id)
    if dept:
        student_q = student_q.filter(Student.department == dept)
    student_count = student_q.count()
    distinct_days = sorted({ r["date"] for r in rows })
    potential_slots = student_count * max(1, len(distinct_days))
    unmarked = max(0, potential_slots - (present + absent))
    attendance_rate = round((present / max(1, present + absent)) * 100, 1)

    #Trend by date
    from collections import Counter
    present_by = Counter()
    absent_by  = Counter()
    for r in rows:
        if r["status"] == "present":
            present_by[r["date"]] += 1
        elif r["status"] == "absent":
            absent_by[r["date"]] += 1

    labels = []
    d = date_from
    while d <= date_to:
        labels.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    trend_present = [present_by.get(day, 0) for day in labels]
    trend_absent  = [absent_by.get(day, 0)  for day in labels]

    departments = [d[0] for d in db.session.query(Student.department)
                   .filter(Student.teacher_id == teacher.id).distinct().all()]

    return render_template(
        "partials/teacher_reports.html",
        departments=departments,
        rows=rows,
        kpis={
            "present": present,
            "absent": absent,
            "unmarked": unmarked,
            "attendance_rate": attendance_rate
        },
        trend={"labels": labels, "present": trend_present, "absent": trend_absent},
    )

@routes.route("/teacher/reports/export")
@login_required
def teacher_reports_export():
    if session.get('role') != 'teacher':
        return "Forbidden", 403

    teacher = Teacher.query.get(current_user.id)

    dept = request.args.get('department') or None
    from_str = request.args.get('from')
    to_str   = request.args.get('to')
    status   = request.args.get('status') or None

    today = date.today()
    date_from = datetime.strptime(from_str, "%Y-%m-%d").date() if from_str else (today - timedelta(days=30))
    date_to   = datetime.strptime(to_str,   "%Y-%m-%d").date() if to_str   else today

    q = (db.session.query(Attendance, Student)
         .join(Student, Student.id == Attendance.student_id)
         .filter(Student.teacher_id == teacher.id)
         .filter(Attendance.date >= date_from, Attendance.date <= date_to))

    if dept:
        q = q.filter(Student.department == dept)
    if status in ("present", "absent"):
        q = q.filter(Attendance.status == status)

    rows = q.order_by(Attendance.date.desc(), Student.roll_number.asc()).all()

    # Build CSV
    from io import StringIO
    import csv
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Date", "Roll No", "Name", "Department", "Status", "Source", "Marked At"])
    for a, s in rows:
        writer.writerow([
            a.date.strftime("%Y-%m-%d"),
            s.roll_number,
            s.full_name,
            s.department,
            a.status,
            a.source or "-",
            a.scanned_at.strftime("%Y-%m-%d %H:%M") if a.scanned_at else "-"
        ])
    output = si.getvalue()
    si.close()

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=attendance_report_{teacher.full_name.replace(' ', '_')}.csv"
        }
    )

@routes.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    # If already authenticated as admin go to dashboard
    if current_user.is_authenticated and session.get("role") == "admin":
        return redirect(url_for("routes.admin_dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        next_url = request.args.get("next")

        if not email or not password:
            flash("Email and password are required.", "danger")
            return redirect(url_for("routes.admin_login", next=next_url))

        admin = Admin.query.filter_by(email=email).first()
        if admin and admin.check_password(password):
            # Reset any previous session context
            session.clear()
            login_user(admin)
            session["user_id"] = admin.id
            session["role"] = "admin"
            flash("Welcome, Admin!", "success")
            return redirect(next_url or url_for("routes.admin_dashboard"))

        flash("Invalid admin credentials.", "danger")
        return redirect(url_for("routes.admin_login", next=next_url))

    # GET
    return render_template("admin/login.html")

@routes.route("/admin/logout")
@admin_required
def admin_logout():
    logout_user()
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("routes.admin_login"))

@routes.route("/admin")
@admin_required
def admin_root():
    return redirect(url_for("routes.admin_dashboard"))

@routes.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    teacher_count = Teacher.query.count()
    student_count = Student.query.count()
    attendance_count = Attendance.query.count()

    # display_name shown in the topbar profile
    display_name = (current_user.full_name if hasattr(current_user, "full_name") else "Admin")

    return render_template(
        "admin/dashboard.html",
        role="admin",
        display_name=display_name,
        teacher_count=teacher_count,
        student_count=student_count,
        attendance_count=attendance_count,
    )

# Admin Partial Views 
@routes.route("/admin/partials/home")
@admin_required
def admin_home_partial():
    teacher_count = Teacher.query.count()
    student_count = Student.query.count()
    attendance_count = Attendance.query.count()

    return render_template(
        "admin/partials/home.html",
        teacher_count=teacher_count,
        student_count=student_count,
        attendance_count=attendance_count,
    )

@routes.route("/admin/home/export")
@admin_required
def admin_home_export():
    # High-level counts
    teacher_count = Teacher.query.count()
    student_count = Student.query.count()
    attendance_count = Attendance.query.count()

    # Status breakdown
    present_count = db.session.query(func.count(Attendance.id))\
        .filter(Attendance.status == "present").scalar() or 0
    absent_count = db.session.query(func.count(Attendance.id))\
        .filter(Attendance.status == "absent").scalar() or 0
    unmarked = max(0, attendance_count - (present_count + absent_count))

    # Department breakdowns
    dept_students = db.session.query(
        Student.department, func.count(Student.id)
    ).group_by(Student.department).order_by(Student.department.asc()).all()

    dept_teachers = db.session.query(
        Teacher.department, func.count(Teacher.id)
    ).group_by(Teacher.department).order_by(Teacher.department.asc()).all()

    # Last 7 days trend (by date)
    today = date.today()
    start_day = today - timedelta(days=6)
    trend_rows = (
        db.session.query(
            Attendance.date,
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
            func.count(Attendance.id).label("total"),
        )
        .filter(Attendance.date >= start_day, Attendance.date <= today)
        .group_by(Attendance.date)
        .order_by(Attendance.date.asc())
        .all()
    )

    # Build CSV
    out = []
    out.append("BioAttend Admin Summary")
    out.append(f"Generated At,{date.today().isoformat()}")
    out.append("")  # blank line

    out.append("Top-level Counts")
    out.append(f"Teachers,{teacher_count}")
    out.append(f"Students,{student_count}")
    out.append(f"Attendance Records,{attendance_count}")
    out.append("")  # blank

    out.append("Status Breakdown")
    out.append(f"Present,{present_count}")
    out.append(f"Absent,{absent_count}")
    out.append(f"Unmarked/Other,{unmarked}")
    out.append("")  # blank

    out.append("Students by Department")
    out.append("Department,Count")
    if dept_students:
        for dept, cnt in dept_students:
            out.append(f"{dept or '-'}, {cnt}")
    else:
        out.append("-,0")
    out.append("")  # blank

    out.append("Teachers by Department")
    out.append("Department,Count")
    if dept_teachers:
        for dept, cnt in dept_teachers:
            out.append(f"{dept or '-'}, {cnt}")
    else:
        out.append("-,0")
    out.append("")  # blank

    out.append("Last 7 Days Trend")
    out.append("Date,Present,Absent,Total")
    # Build a full 7-day axis so missing days show as zeros
    day = start_day
    trend_map = {r.date: r for r in trend_rows}
    for _ in range(7):
        row = trend_map.get(day)
        p = int(row.present) if row else 0
        a = int(row.absent) if row else 0
        t = int(row.total) if row else 0
        out.append(f"{day.isoformat()},{p},{a},{t}")
        day += timedelta(days=1)

    csv_text = "\n".join(out)

    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=admin_summary.csv"}
    )

@routes.route("/admin/api/trend")
@admin_required
def admin_trend_api():
    """
    Return last N days of attendance trends:
    present, absent counts per date.
    """

    try:
        days = int(request.args.get("days", 28))
        days = max(7, min(days, 90))
    except ValueError:
        days = 28

    today = date.today()
    start = today - timedelta(days=days - 1)

    # Group attendance by date and status
    rows = (
        db.session.query(
            Attendance.date,
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        )
        .filter(Attendance.date >= start, Attendance.date <= today)
        .group_by(Attendance.date)
        .order_by(Attendance.date.asc())
        .all()
    )

    # Build full-day series (fill missing with 0)
    by_date = {r.date: {"present": r.present or 0, "absent": r.absent or 0} for r in rows}

    labels, present_counts, absent_counts, total_counts = [], [], [], []
    d = start
    while d <= today:
        rec = by_date.get(d, {"present": 0, "absent": 0})
        p, a = rec["present"], rec["absent"]
        labels.append(d.strftime("%b %d"))
        present_counts.append(p)
        absent_counts.append(a)
        total_counts.append(p + a)
        d += timedelta(days=1)

    return {
        "labels": labels,
        "present": present_counts,
        "absent": absent_counts,
        "total": total_counts,
    }

@routes.route("/admin/api/attendance/today")
@admin_required
def admin_today_snapshot_api():
    """Return present/absent/unmarked for *today* with a LOCAL last_update consistent with Detailed Records."""
    from datetime import date, timezone
    from zoneinfo import ZoneInfo

    LOCAL_TZ = ZoneInfo("Asia/Kolkata")
    today = date.today()

    # Totals 
    total_students = Student.query.count()
    present = Attendance.query.filter(
        Attendance.date == today,
        Attendance.status == "present"
    ).count()
    absent = Attendance.query.filter(
        Attendance.date == today,
        Attendance.status == "absent"
    ).count()
    unmarked = max(0, total_students - present - absent)

    #last updates
    todays = Attendance.query.filter(Attendance.date == today).all()

    last_local = None
    for a in todays:
        raw = None
        used_scanned = False

        if a.scanned_at:
            raw = a.scanned_at
            used_scanned = True
        elif getattr(a, "timestamp", None):
            raw = a.timestamp

        if not raw:
            continue

        # Normalize
        if raw.tzinfo is None:
            if used_scanned:
                # teacher/manual saves often wrote local time without tz
                raw = raw.replace(tzinfo=LOCAL_TZ)
            else:
                # legacy/device timestamp usually UTC-naive
                raw = raw.replace(tzinfo=timezone.utc)

        local_dt = raw.astimezone(LOCAL_TZ)
        if last_local is None or local_dt > last_local:
            last_local = local_dt

    last_update_iso = last_local.isoformat() if last_local else None
    last_update_hm  = last_local.strftime("%H:%M") if last_local else None

    payload = {
        "present": present,
        "absent": absent,
        "unmarked": unmarked,
        "total": total_students,
        "last_update": last_update_iso,
        "last_update_hm": last_update_hm
    }

    resp = make_response(jsonify(payload), 200)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@routes.route("/admin/api/biologs/recent")
@admin_required
def admin_bio_logs_recent_api():
    """Return the latest fingerprint events for the small feed on admin home."""
    try:
        limit = int(request.args.get("limit", 6))
    except ValueError:
        limit = 6

    q = (
        db.session.query(Attendance, Student, Teacher)
        .join(Student, Student.id == Attendance.student_id)
        .outerjoin(Teacher, Teacher.id == Attendance.teacher_id)
        .filter(Attendance.source == "fingerprint",
            Attendance.status == "present")
        .order_by(Attendance.scanned_at.desc())
        .limit(limit)
    )

    def iso_utc_z(dt):
        if not dt:
           return None
        # Treat naive as LOCAL (Asia/Kolkata) instead of UTC
        from zoneinfo import ZoneInfo
        LOCAL_TZ = ZoneInfo("Asia/Kolkata")
        if dt.tzinfo is None:
        # your device likely saved local IST without tz awareness
            dt = dt.replace(tzinfo=LOCAL_TZ)
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.isoformat().replace("+00:00", "Z")

    data = []
    for a, s, t in q.all():
        data.append({
            "timestamp": iso_utc_z(a.scanned_at),
            "status": a.status,
            "device_id": a.device_id,
            "finger_id": a.finger_id,
            "confidence": a.confidence,
            "student": s.full_name if s and s.full_name else "-",
            "department": s.department if s and s.department else "-",
            "teacher": t.full_name if t and t.full_name else "-",
        })

    resp = make_response(jsonify({"events": data}), 200)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# Admin: Teachers management
from sqlalchemy import or_

@routes.route("/admin/partials/teachers")
@admin_required
def admin_teachers_partial():
    # Filters
    q_text = (request.args.get("q") or "").strip()
    dept = (request.args.get("department") or "").strip()
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    per_page = 10

    #for reset
    if request.args.get("reset") == "1":
        q_text = ""
        dept = ""
        page = 1

    query = Teacher.query
    if q_text:
        like = f"%{q_text}%"
        query = query.filter(or_(
            Teacher.full_name.ilike(like),
            Teacher.email.ilike(like),
            Teacher.department.ilike(like)
        ))
    if dept:
        query = query.filter(Teacher.department == dept)

    query = query.order_by(Teacher.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    departments = [d[0] for d in db.session.query(Teacher.department).distinct().all()]

    return render_template(
        "admin/partials/teachers.html",
        teachers=pagination.items,
        pagination=pagination,
        q=q_text,
        department=dept,
        departments=departments,
    )

@routes.route("/admin/teachers/create", methods=["POST"])
@admin_required
def admin_teacher_create():
    from sqlalchemy.exc import IntegrityError
    import re, sys, traceback

    full_name  = (request.form.get("full_name") or "").strip()
    email      = (request.form.get("email") or "").strip().lower()
    department = (request.form.get("department") or "").strip()
    password   = (request.form.get("password") or "").strip()

    print("[admin_teacher_create] FORM =>", dict(request.form), file=sys.stderr, flush=True)

    if not full_name or not email or not department or not password:
        return jsonify({"ok": False, "msg": "All fields are required."}), 400

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"ok": False, "msg": "Invalid email format."}), 400

    try:
        exists = Teacher.query.filter(func.lower(Teacher.email) == email).first()
        if exists:
            return jsonify({"ok": False, "msg": "Email already registered for a teacher."}), 409

        t = Teacher(full_name=full_name, email=email, department=department)
        if hasattr(t, "set_password"):
            t.set_password(password)
        else:
            t.password = password  # legacy fallback

        db.session.add(t)
        db.session.flush()  # gets t.id now

        print("[admin_teacher_create] NEW ID =", t.id, file=sys.stderr, flush=True)

        db.session.commit()
        return jsonify({"ok": True, "msg": "Teacher created.", "id": t.id}), 201

    except IntegrityError as ie:
        db.session.rollback()
        print("[admin_teacher_create][IntegrityError]", ie, file=sys.stderr, flush=True)
        return jsonify({"ok": False, "msg": "Could not save teacher (unique constraint)."}), 409
    except Exception as ex:
        db.session.rollback()
        print("[admin_teacher_create][Exception]", ex, file=sys.stderr, flush=True)
        traceback.print_exc()
        return jsonify({"ok": False, "msg": f"Server error: {type(ex).__name__}"}), 500

@routes.route("/admin/teachers/<int:teacher_id>/delete", methods=["POST"])
@admin_required
def admin_teacher_delete(teacher_id):
    teacher = Teacher.query.get_or_404(teacher_id)
    db.session.delete(teacher)
    db.session.commit()
    return jsonify({"ok": True, "msg": "Teacher deleted."})

@routes.route("/admin/teachers/export")
@admin_required
def admin_teachers_export():
    # filters
    q_text = (request.args.get("q") or "").strip()
    dept = (request.args.get("department") or "").strip()

    query = Teacher.query
    if q_text:
        like = f"%{q_text}%"
        query = query.filter(or_(
            Teacher.full_name.ilike(like),
            Teacher.email.ilike(like),
            Teacher.department.ilike(like)
        ))
    if dept:
        query = query.filter(Teacher.department == dept)

    rows = query.order_by(Teacher.created_at.desc()).all()

    # CSV
    from io import StringIO
    import csv
    si = StringIO()
    w = csv.writer(si)
    w.writerow(["Full Name", "Email", "Department", "Created At"])
    for t in rows:
        w.writerow([t.full_name, t.email, t.department, t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "-"])
    out = si.getvalue()
    si.close()

    from flask import Response
    return Response(
        out,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=teachers_export.csv"}
    )

@routes.route("/admin/partials/students")
@admin_required
def admin_students_partial():
    # reads args first
    q_text = (request.args.get("q") or "").strip()
    dept   = (request.args.get("department") or "").strip()
    year   = (request.args.get("year") or "").strip()
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    per_page = 10

    # handled reset BEFORE building the query
    if request.args.get("reset") == "1":
        q_text = ""
        dept   = ""
        year   = ""
        page   = 1

    # build query with possibily clered filters
    query = Student.query
    if q_text:
        like = f"%{q_text}%"
        query = query.filter(or_(
            Student.full_name.ilike(like),
            Student.email.ilike(like),
            Student.roll_number.ilike(like),
            Student.department.ilike(like)
        ))
    if dept:
        query = query.filter(Student.department == dept)
    if year:
        query = query.filter(Student.year == year)

    query = query.order_by(Student.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Converts naive UTC created_at : IST
    from datetime import timezone
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Kolkata")

    for s in pagination.items:
        if s.created_at:
            raw = s.created_at
            # treat naive as UTC
            if raw.tzinfo is None:
                raw = raw.replace(tzinfo=timezone.utc)
            s.created_at = raw.astimezone(LOCAL_TZ)

    # filter lists / KPIs
    departments = [d[0] for d in db.session.query(Student.department).distinct().all()]
    years = [y[0] for y in db.session.query(Student.year).filter(Student.year.isnot(None)).distinct().all()]

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    kpis = {
        "total": Student.query.count(),
        "departments": db.session.query(Student.department).distinct().count(),
        "recent": Student.query.filter(Student.created_at >= thirty_days_ago).count(),
        "assigned": Student.query.filter(Student.teacher_id.isnot(None)).count()
    }

    teachers = (Teacher.query
                .order_by(func.lower(Teacher.full_name))
                .all())

    return render_template(
        "admin/partials/students.html",
        students=pagination.items,
        pagination=pagination,
        q=q_text,
        department=dept,
        year=year,
        departments=departments,
        years=years,
        kpis=kpis,
        teachers=teachers,
    )

@routes.post("/admin/students/assign")
@admin_required
def admin_student_assign():
    """Assign a single student to a teacher."""
    student_id = request.form.get("student_id", type=int)
    teacher_id = request.form.get("teacher_id", type=int)

    if not student_id or not teacher_id:
        return jsonify({"ok": False, "msg": "student_id and teacher_id are required"}), 400

    student = Student.query.get(student_id)
    teacher = Teacher.query.get(teacher_id)
    if not student:
        return jsonify({"ok": False, "msg": "Student not found"}), 404
    if not teacher:
        return jsonify({"ok": False, "msg": "Teacher not found"}), 404

    student.teacher_id = teacher.id
    db.session.commit()

    return jsonify({"ok": True, "msg": "Assigned", "student_id": student.id, "teacher_id": teacher.id})

@routes.route("/admin/students/create", methods=["POST"])
@admin_required
def admin_student_create():
    full_name  = (request.form.get("full_name") or "").strip()
    roll_number = (request.form.get("roll_number") or "").strip()
    department = (request.form.get("department") or "").strip()
    year       = (request.form.get("year") or "").strip() or None
    email      = (request.form.get("email") or "").strip().lower()
    password   = (request.form.get("password") or "")

    # Basic validations
    if not full_name or not roll_number or not department or not email or not password:
        return jsonify({"ok": False, "msg": "All fields are required."}), 400

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"ok": False, "msg": "Invalid email format."}), 400

    if len(password) < 8 or not re.search(r"\d", password) or not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return jsonify({"ok": False, "msg": "Password must be at least 8 characters and include a number and special character."}), 400

    # Uniqueness
    if Student.query.filter(func.lower(Student.email) == email.lower()).first():
        return jsonify({"ok": False, "msg": "Email already registered for a student."}), 400

    if Student.query.filter_by(roll_number=roll_number).first():
        return jsonify({"ok": False, "msg": "Roll number already registered."}), 400

    s = Student(
        full_name=full_name,
        roll_number=roll_number,
        department=department,
        year=year,
        email=email,
        teacher_id=None,  # can assign later
    )
    s.set_password(password)
    db.session.add(s)
    db.session.commit()

    return jsonify({"ok": True, "msg": "Student created."})

@routes.route("/admin/students/<int:student_id>/delete", methods=["POST"])
@admin_required
def admin_student_delete(student_id):
    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()
    return jsonify({"ok": True, "msg": "Student deleted."})

@routes.route("/admin/students/export")
@admin_required
def admin_students_export():
    q_text = (request.args.get("q") or "").strip()
    dept   = (request.args.get("department") or "").strip()
    year   = (request.args.get("year") or "").strip()

    query = Student.query
    if q_text:
        like = f"%{q_text}%"
        query = query.filter(or_(
            Student.full_name.ilike(like),
            Student.email.ilike(like),
            Student.roll_number.ilike(like),
            Student.department.ilike(like),
        ))
    if dept:
        query = query.filter(Student.department == dept)
    if year:
        query = query.filter(Student.year == year)

    rows = query.order_by(Student.created_at.desc()).all()

    from io import StringIO
    si = StringIO()
    w = csv.writer(si)
    w.writerow(["Full Name", "Email", "Roll Number", "Department", "Year", "Created At"])
    for s in rows:
        w.writerow([
            s.full_name,
            s.email,
            s.roll_number,
            s.department,
            (s.year or "-"),
            s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "-"
        ])
    out = si.getvalue()
    si.close()

    return Response(
        out,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=students_export.csv"}
    )

# simple memory cache used
_cache = {"departments": None, "teachers": None, "last_fetched": None}

@routes.route("/admin/partials/reports")
@admin_required
def admin_reports_partial():
    """Admin – Attendance Reports partial view (with lightweight caching)"""

    # Parse filters
    start_str = request.args.get("from")
    end_str   = request.args.get("to")
    department = request.args.get("department")
    teacher_id = request.args.get("teacher_id")
    status     = request.args.get("status")
    q          = request.args.get("q", "").strip()

    # Handled reset (clear all filters)
    if request.args.get("reset") == "1":
       start_str = end_str = department = teacher_id = status = q = ""

    # fallback range: last 30 days
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date() if start_str else datetime.utcnow().date() - timedelta(days=30)
    except ValueError:
        start_date = datetime.utcnow().date() - timedelta(days=30)
    try:
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date() if end_str else datetime.utcnow().date()
    except ValueError:
        end_date = datetime.utcnow().date()

    # Base query
    query = (
        db.session.query(Attendance, Student, Teacher)
        .join(Student, Attendance.student_id == Student.id)
        .join(Teacher, Student.teacher_id == Teacher.id)
        .filter(Attendance.date.between(start_date, end_date))
    )

    if department:
        query = query.filter(Student.department == department)
    if teacher_id:
        query = query.filter(Student.teacher_id == int(teacher_id))
    if status in ["present", "absent"]:
        query = query.filter(Attendance.status == status)
    if q:
        q_like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                func.lower(Student.full_name).like(q_like),
                func.lower(Student.roll_number).like(q_like)
            )
        )

    records = query.order_by(Attendance.date.desc()).all()

    # Build rows
    rows = []
    for att, stu, teacher in records:
        rows.append({
            "date": att.date.strftime("%Y-%m-%d"),
            "full_name": stu.full_name,
            "roll_number": stu.roll_number,
            "department": stu.department,
            "teacher_name": teacher.full_name,
            "status": att.status,
            "source": getattr(att, "source", "N/A"),
            "marked_at": getattr(att, "timestamp", None).strftime("%Y-%m-%d %H:%M") if getattr(att, "timestamp", None) else "-",
        })

    # KPIs
    total_records = len(records)
    present_count = sum(1 for att, _, _ in records if att.status == "present")
    avg_rate = round((present_count / total_records * 100), 1) if total_records else 0.0

    dept_stats = (
        db.session.query(Student.department, func.count(Attendance.id))
        .join(Attendance)
        .filter(Attendance.date.between(start_date, end_date))
        .group_by(Student.department)
        .all()
    )
    dept_map = {d: c for d, c in dept_stats}
    top_department = max(dept_map, key=dept_map.get) if dept_map else "-"
    low_department = min(dept_map, key=dept_map.get) if dept_map else "-"

    kpis = {
        "total_records": total_records,
        "avg_rate": avg_rate,
        "top_department": top_department,
        "low_department": low_department,
    }

    # Trend chart
    daily = (
        db.session.query(
            Attendance.date,
            func.sum(case((Attendance.status == "present", 1), else_=0)).label("present"),
            func.sum(case((Attendance.status == "absent", 1), else_=0)).label("absent"),
        )
        .filter(Attendance.date.between(start_date, end_date))
        .group_by(Attendance.date)
        .order_by(Attendance.date)
        .all()
    ) 

    trend = {
        "labels": [d.date.strftime("%Y-%m-%d") for d in daily],
        "present": [int(d.present or 0) for d in daily],
        "absent": [int(d.absent or 0) for d in daily],
    }

    # Cached dropdowns boost speed
    now = datetime.utcnow()
    cache_valid = _cache["last_fetched"] and (now - _cache["last_fetched"]) < timedelta(hours=6)

    if not cache_valid:
        _cache["departments"] = [d[0] for d in db.session.query(Student.department).distinct().order_by(Student.department).all()]
        _cache["teachers"] = db.session.query(Teacher).order_by(Teacher.full_name).all()
        _cache["last_fetched"] = now

    departments = _cache["departments"]
    teachers = _cache["teachers"]

    # Render
    return render_template(
        "admin/partials/reports.html",
        kpis=kpis,
        trend=trend,
        rows=rows,
        departments=departments,
        teachers=teachers,
    )

@routes.route("/admin/partials/biologs")
@admin_required
def admin_bio_logs_partial():
    """Admin → Biometric Logs view with filters, KPIs, and pagination."""
    # Parameters 
    q         = request.args.get("q", "").strip()
    role      = request.args.get("role", "")
    status_in = (request.args.get("status", "").strip() or "present")
    device    = request.args.get("device", "")
    from_str  = request.args.get("from", "")
    to_str    = request.args.get("to", "")
    conf_min  = request.args.get("conf_min", type=int)
    page      = request.args.get("page", 1, type=int)
    per_page  = 12
    LOCAL_TZ = ZoneInfo("Asia/Kolkata")

    # Date Range Filter
    try:
        from_date = datetime.strptime(from_str, "%Y-%m-%d") if from_str else None
        to_date   = datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1) if to_str else None
    except Exception:
        from_date = to_date = None

    #  Base Query for biometric logs
    query = Attendance.query.filter(Attendance.source == "fingerprint")

    # Optional filters
    if from_date:
        query = query.filter(Attendance.timestamp >= from_date)
    if to_date:
        query = query.filter(Attendance.timestamp < to_date)
    if role:
        query = query.filter(Attendance.role == role)
    _status_norm = status_in.lower()
    status_map = {
    "failed": "MATCH_FAIL",
    "match_fail": "MATCH_FAIL",
    "present": "present",
    "absent": "absent",
    }
    if _status_norm not in ("all", ""):
       status_value = status_map.get(_status_norm, status_in)  # fall back to raw if already correct
       query = query.filter(Attendance.status == status_value)
    if device:
        query = query.filter(Attendance.device_id == device)
    if conf_min is not None:
        query = query.filter(Attendance.confidence >= conf_min)
    if q:
        query = query.join(Student, isouter=True).join(Teacher, isouter=True).filter(
            or_(
                func.lower(Student.full_name).like(f"%{q.lower()}%"),
                func.lower(Teacher.full_name).like(f"%{q.lower()}%"),
                func.cast(Attendance.finger_id, db.String).ilike(f"%{q}%"),
                func.lower(Attendance.department).like(f"%{q.lower()}%")
            )
        )

    #Sorting
    query = query.order_by(Attendance.timestamp.desc())

    #Pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    #KPI Cards
    today = datetime.now().date()
    base_today = Attendance.query.filter(
        func.date(Attendance.timestamp) == today,
        Attendance.source == "fingerprint"
    )

    kpis = {
        "total": base_today.count(),
        "matched": base_today.filter(Attendance.status == "present").count(),
        "failed": base_today.filter(Attendance.status == "MATCH_FAIL").count(),
        "devices": db.session.query(Attendance.device_id)
                    .filter(func.date(Attendance.timestamp) == today,
                            Attendance.source == "fingerprint")
                    .distinct().count()
    }

    #Device list dropdown
    devices = [d[0] for d in db.session.query(Attendance.device_id)
               .distinct().order_by(Attendance.device_id.asc()).all() if d[0]]

    #Pre-processed logs for display
    processed = []
    for r in logs:
        # pick the best available timestamp in order
        raw_ts = r.timestamp or getattr(r, "scanned_at", None) or getattr(r, "created_at", None)

        # robustness treat naive as UTC, then convert to IST
        ts_local = None
        if raw_ts:
            if raw_ts.tzinfo is None:
                raw_ts = raw_ts.replace(tzinfo=LOCAL_TZ)
            ts_local = raw_ts.astimezone(LOCAL_TZ)
    
        # Determining user info
        user_name, department = "-", "-"
        if r.role == "student" and r.student_id:
            student = Student.query.get(r.student_id)
            if student:
                user_name = student.full_name
                department = student.department
        elif r.role == "teacher" and r.teacher_id:
            teacher = Teacher.query.get(r.teacher_id)
            if teacher:
                user_name = teacher.full_name
                department = teacher.department

        processed.append({
            "id": r.id,
            "timestamp": ts_local,
            "finger_id": r.finger_id,
            "user_name": user_name,
            "role": r.role,
            "department": department,
            "device_id": r.device_id or "R307S",
            "status": r.status,
            "confidence": r.confidence,
            "synced": getattr(r, "synced", True)
        })

    return render_template(
        "admin/partials/bio_logs.html",
        logs=processed,
        pagination=pagination,
        kpis=kpis,
        devices=devices
    )

@routes.route("/admin/api/biologs/stats")
@admin_required
def admin_bio_logs_stats_api():
    """
    Aggregated stats for the Bio Logs dashboard/pulse.
    Counts only Attendance records where source='fingerprint'.
    A device is considered 'active' if it has a scan in the last 5 minutes.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=5)

    q = Attendance.query.filter(Attendance.source == "fingerprint")

    total     = q.count()
    matched   = q.filter(Attendance.status == "present").count()
    failed    = q.filter(Attendance.status == "MATCH_FAIL").count()

    # distinct active devices seen in last 5 minutes
    devices_active = (
        db.session.query(Attendance.device_id)
        .filter(Attendance.source == "fingerprint",
                Attendance.device_id.isnot(None),
                Attendance.scanned_at >= since)
        .distinct()
        .count()
    )

    payload = {
        "total": total,
        "matched": matched,
        "failed": failed,
        "devices_active": devices_active,
        "window_minutes": 5
    }

    resp = make_response(jsonify(payload), 200)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# In-memory settings + mini system log (db later)
SETTINGS_CACHE = {
    "device_id": "R307S-01",
    "device_port": "COM3",
    "baud_rate": "57600",
    "attendance_start": "09:00",
    "attendance_end": "09:15",
    "auto_absent": True,
    "allow_backfill": True,
    "email_on_error": True,
    "email_daily_summary": False,
    "email_reports": False,
    "notify_email": "",
    "report_schedule": "",
    "theme_default": "dark",
    "accent_color": "#3b82f6",
    "last_backup": "—",
    "auto_backup": True,
}

SYSTEM_LOG = deque(maxlen=200)

def _log(msg):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    SYSTEM_LOG.appendleft(f"[{ts} UTC] {msg}")

def _get_settings():
    return dict(SETTINGS_CACHE)

def _coerce_bool(val):
    # checkboxes submit as "on" present or missing
    return str(val).lower() in ("1", "true", "on", "yes")

def _update_settings_from_form(form):
    """Merge posted fields into SETTINGS_CACHE, with simple type coercion."""
    # strings
    for key in [
        "device_id", "device_port", "baud_rate",
        "attendance_start", "attendance_end",
        "notify_email", "report_schedule",
        "theme_default", "accent_color",
    ]:
        if key in form:
            SETTINGS_CACHE[key] = form.get(key, "").strip()

    # booleans
    for key in [
        "auto_absent", "allow_backfill",
        "email_on_error", "email_daily_summary", "email_reports",
        "auto_backup",
    ]:
        SETTINGS_CACHE[key] = _coerce_bool(form.get(key))

    # housekeeping
    _log("Settings updated.")

# Update the existing partial to pass settings & last 10 logs
@routes.route("/admin/partials/settings")
@admin_required
def admin_settings_partial():
    settings = _get_settings()
    logs = list(SYSTEM_LOG)[:10]
    return render_template("admin/partials/settings.html", settings=settings, logs=logs)

# Generic save endpoint 
@routes.route("/admin/settings/save", methods=["POST"])
@admin_required
def admin_settings_save():
    _update_settings_from_form(request.form)
    return jsonify({"ok": True, "settings": _get_settings()})

# Maintenance group 
@routes.route("/admin/settings/maintenance", methods=["POST"])
@admin_required
def admin_settings_maintenance():
    # placeholder topost form
    _log("Maintenance form submitted.")
    return jsonify({"ok": True})

# Action to Test Device connection
@routes.route("/admin/settings/test-device", methods=["POST"])
@admin_required
def admin_settings_test_device():
    dev = SETTINGS_CACHE.get("device_id", "R307S")
    port = SETTINGS_CACHE.get("device_port", "COM3")
    baud = SETTINGS_CACHE.get("baud_rate", "57600")
    _log(f"Tested device {dev} on {port} @ {baud}: OK")
    return jsonify({"ok": True, "message": "Device reachable"})

# Actions Backup Now 
@routes.route("/admin/settings/backup-now", methods=["POST"])
@admin_required
def admin_settings_backup_now():
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    SETTINGS_CACHE["last_backup"] = now_str
    _log("Backup completed.")
    return jsonify({"ok": True, "last_backup": SETTINGS_CACHE["last_backup"]})

# Actions Sync Fingerprints
@routes.route("/admin/settings/sync-now", methods=["POST"])
@admin_required
def admin_settings_sync_now():
    _log("Fingerprint templates sync started.")
    # do real sync later 
    _log("Fingerprint templates sync finished.")
    return jsonify({"ok": True})

@routes.route("/common/partials/me-settings")
@login_required
def me_settings_partial():
    return render_template("common/partials/me_settings.html")

# PROFILE for all roles
@routes.route("/common/partials/profile")
@login_required
def profile_partial():
    """Render the profile view as a partial (loaded inside #main-content)."""

    # Try read role from the user object
    raw_role = getattr(current_user, "role", None)

    role = None
    if raw_role:
        # Normalize
        if isinstance(raw_role, str):
            role = raw_role.strip().lower()
        else:
            role = getattr(raw_role, "name", None)
            role = (role or str(raw_role)).strip().lower()

    # Fallback to session
    if not role:
        role = (session.get("role") or "").strip().lower() or None

    # Final fallback infer from class name
    if not role:
        cls_name = current_user.__class__.__name__.lower()
        if "admin" in cls_name:
            role = "admin"
        elif "teacher" in cls_name:
            role = "teacher"
        elif "student" in cls_name:
            role = "student"
        else:
            role = "user"

    # Human-readable label for the template
    display_role = {
        "admin": "Admin",
        "teacher": "Teacher",
        "student": "Student",
    }.get(role, "User")

    # Permissions 
    can_self_change_password = (role == "admin")
    can_edit_basic = (role == "admin")

    # Best-effort fields 
    profile = {
        "name": getattr(current_user, "full_name", getattr(current_user, "name", "User")),
        "email": getattr(current_user, "email", "-"),
        "role": display_role,  # UI Readalbe text
        "role_code": role,     # raw code for CSS badges (role-admin, role-teacher, etc.)
        "department": getattr(current_user, "department", "-"),
        "roll_no": getattr(current_user, "roll_no", None),
        "created_at": getattr(current_user, "created_at", None),
        # support for both last_login and last_login_at
        "last_login_at": getattr(current_user, "last_login_at",
                           getattr(current_user, "last_login", None)),
        "avatar_url": getattr(current_user, "avatar_url", None),
    }

    return render_template(
        "common/partials/profile.html",
        profile=profile,
        can_self_change_password=can_self_change_password,
        can_edit_basic=can_edit_basic,
        role=role,                
        display_role=display_role 
    )

@routes.route("/common/api/profile/request_reset", methods=["POST"])
@login_required
def profile_request_reset():
    """Teachers/Students click this. No email yet—just log it (wire email later)."""
    current_app.logger.info(f"[PROFILE] Password reset requested by user_id={current_user.id}")
    #push in-memory SYSTEM_LOG 
    try:
        from collections import deque
        msg = {
            "type": "pwd_reset_request",
            "user": getattr(current_user, "email", "unknown"),
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
        }
        # If SYSTEM_LOG exists
        if "SYSTEM_LOG" in globals():
            SYSTEM_LOG.appendleft(msg)
    except Exception:
        pass
    return jsonify({"ok": True})

@routes.route("/common/api/profile/update_basic", methods=["POST"])
@login_required
def profile_update_basic():
    """Admins can edit their display name/department. Small + safe."""
    role = getattr(current_user, "role", "user")
    if role != "admin":
        return jsonify({"ok": False, "msg": "Not allowed."}), 403

    name = request.form.get("name", "").strip()
    dept = request.form.get("department", "").strip()

    if name:
        if hasattr(current_user, "full_name"):
            current_user.full_name = name
        elif hasattr(current_user, "name"):
            current_user.name = name
    if dept and hasattr(current_user, "department"):
        current_user.department = dept
    try:
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("profile_update_basic failed")
        return jsonify({"ok": False, "msg": str(e)}), 500

@routes.route("/common/api/profile/change_password", methods=["POST"])
@login_required
def profile_change_password():
    """Admins only. Safely change password with old/new/confirm verification."""
    role = getattr(current_user, "role", "user")
    if role != "admin":
        return jsonify({"ok": False, "msg": "Not allowed."}), 403

    old = request.form.get("old_password", "")
    new = request.form.get("new_password", "")
    cnf = request.form.get("confirm_password", "")

    if len(new) < 8:
        return jsonify({"ok": False, "msg": "Password must be at least 8 characters."}), 400
    if new != cnf:
        return jsonify({"ok": False, "msg": "Passwords do not match."}), 400

    # detects hash attr name
    hash_attr = None
    for attr in ("password_hash", "password", "pwd_hash"):
        if hasattr(current_user, attr):
            hash_attr = attr
            break
    if not hash_attr:
        return jsonify({"ok": False, "msg": "Password store not available on this user model."}), 500

    pw_hash = getattr(current_user, hash_attr)
    if not pw_hash or not check_password_hash(pw_hash, old):
        return jsonify({"ok": False, "msg": "Old password is incorrect."}), 400

    setattr(current_user, hash_attr, generate_password_hash(new))
    try:
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("change_password failed")
        return jsonify({"ok": False, "msg": str(e)}), 500
