from app import create_app, db
from app.models import Student, Teacher

app = create_app()

with app.app_context():
    #Pick the teacher (default)
    teacher = Teacher.query.filter_by(email="teacher@test.com").first()
    if not teacher:
        print("No teacher found with that email. Update the email in this script.")
        exit()

    orphan_students = Student.query.filter(Student.teacher_id.is_(None)).all()
    if not orphan_students:
        print("No orphan students found.")
    else:
        for s in orphan_students:
            s.teacher_id = teacher.id
            print(f"Linked {s.full_name} to {teacher.full_name}")

        db.session.commit()
        print(f"Fixed {len(orphan_students)} orphan students.")
