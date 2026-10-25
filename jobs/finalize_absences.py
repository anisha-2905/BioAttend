from __future__ import annotations
import argparse
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from app import create_app
from app.extensions import db
from app.models import Student, Attendance

IST = ZoneInfo("Asia/Kolkata")

def compute_target_date(mode: str | None, date_str: str | None) -> date:
    now_ist = datetime.now(IST)
    if date_str:
        #Expects YYYY-MM-DD (in local time)
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    if mode == "yesterday":
        return (now_ist - timedelta(days=1)).date()
    #Default: finalize "today" if day is over, else "yesterday"
    if now_ist.hour >= 18:  #after 6 PM
        return now_ist.date()
    return (now_ist - timedelta(days=1)).date()

def finalize_absences(target: date) -> dict:
    """
    For every student, ensure there is exactly one Attendance row for `target`.
    If none exists, insert an 'absent' record. Idempotent.
    DOES NOT create fingerprint logs (source != 'fingerprint').
    """
    added = 0
    updated = 0

    #Pull all students once
    students = Student.query.all()

    for s in students:
        #Check if an attendance row already exists for this student & date
        att = Attendance.query.filter_by(student_id=s.id, date=target).first()
        if att:
            #If someone manually set present/absent leave it as-is
            #enforce absent if status is unmarked)
            if not att.status or att.status not in ("present", "absent"):
                att.status = "absent"
                att.source = att.source or "auto-absent"
                updated += 1
            continue

        #Creates a new 'absent' row (minimal fields; NOT appears in Bio Logs)
        new_att = Attendance(
            student_id=s.id,
            teacher_id=getattr(s, "teacher_id", None),
            department=s.department,
            date=target,
            status="absent",
            source="auto-absent",   #NOT "fingerprint" so kept out of Biometric Logs UI
            device_id=None,
            finger_id=None,
            confidence=None,
            role="student",
            remarks=None,
            scanned_at=datetime.now(timezone.utc),
        )
        db.session.add(new_att)
        added += 1

    db.session.commit()
    return {"date": target.isoformat(), "added": added, "updated": updated, "total_students": len(students)}

def main():
    parser = argparse.ArgumentParser(description="Finalize daily absences for BioAttend.")
    parser.add_argument("--date", help="YYYY-MM-DD (local IST). If omitted, smart default is used.")
    parser.add_argument("--yesterday", action="store_true", help="Finalize yesterday explicitly.")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        target = compute_target_date("yesterday" if args.yesterday else None, args.date)
        result = finalize_absences(target)
        print(f"[finalize_absences] {result}", flush=True)

        #ensures tasks exit
        import sys
        sys.exit(0)

if __name__ == "__main__":
    main()
