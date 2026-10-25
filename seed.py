from datetime import date, timedelta
import random

from app import create_app, db
from app.models import Student, Attendance, Teacher, Admin

#Create app context
app = create_app()

with app.app_context():
    #Ensures at least one Teacher exists
    teacher = Teacher.query.first()
    if not teacher:
        teacher = Teacher(
            full_name="Demo Teacher",
            email="demo.teacher@example.com",
            department="Computer Science"
        )
        teacher.set_password("password123")
        db.session.add(teacher)
        db.session.commit()
        print("Demo Teacher added.")
    else:
        print(f"Teacher already exists: {teacher.full_name}")

    #Ensure at least some Students exist
    students = Student.query.filter_by(teacher_id=teacher.id).all()
    if not students:
        dummy_students = [
            Student(
                full_name=f"Student {i}",
                roll_number=f"CS10{i}",
                department=random.choice(["Computer Science", "Electronics", "Mechanical"]),
                email=f"student{i}@example.com",
                teacher_id=teacher.id
            )
            for i in range(1, 6)  #5 dummy students
        ]
        for s in dummy_students:
            s.set_password("password123")
            db.session.add(s)

        db.session.commit()
        print("Dummy Students added.")
    else:
        print(f"Students already exist: {len(students)} linked to {teacher.full_name}")

    #Seed dummy attendance for first student only (dont flood db)
    student = Student.query.first()
    if student:
        if Attendance.query.filter_by(student_id=student.id).count() == 0:
            today = date.today()
            for i in range(10):
                record_date = today - timedelta(days=i)
                status = random.choice(["present", "absent"])
                record = Attendance(student_id=student.id, date=record_date, status=status)
                db.session.add(record)

            db.session.commit()
            print(f"Dummy attendance added for student: {student.full_name}")
        else:
            print("Attendance records already exist. No dummy data added.")

    #Ensures at least one Admin exists
    admin = Admin.query.filter_by(email="admin@bioattend.local").first()
    if not admin:
        admin = Admin(
            full_name="System Admin",
            email="admin@bioattend.local"
        )
        admin.set_password("Strong!Passw0rd")
        db.session.add(admin)
        db.session.commit()
        print("Admin user added: admin@bioattend.local / Strong!Passw0rd")
    else:
        print(f"Admin already exists: {admin.full_name} ({admin.email})")
