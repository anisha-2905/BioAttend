from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, date, timezone
from app.models import db, Student, Attendance, BiometricTemplate
from app.extensions import limiter
from app.utils.biocrypt import encrypt_template, sha256_hex
import base64
import logging

api = Blueprint("api", __name__, url_prefix="/api")

#simple API-key guard
def require_api_key(req):
    sent = req.headers.get("X-API-KEY")  # standardize to uppercase spelling
    expected = current_app.config.get("DEVICE_API_KEY")
    return sent and expected and sent == expected

# health
@api.get("/ping")
def ping():
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return jsonify({
        "ok": True,
        "server_time": datetime.utcnow().isoformat() + "Z"
    })

# attendance ingest
@api.post("/mark_attendance")
def mark_attendance():
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    # Expected body: { "student_id": 123, "status": "present", "scanned_at": "2025-08-24T09:10:00Z" }
    student_id = data.get("student_id")
    status = (data.get("status") or "present").lower()
    scanned_at = data.get("scanned_at")

    if not student_id:
        return jsonify({"ok": False, "error": "student_id required"}), 400
    if status not in {"present", "absent"}:
        return jsonify({"ok": False, "error": "Invalid status"}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404

    # Parse timestamp
    dt = None
    if scanned_at:
        try:
            # handle trailing Z or offset-less ISO
            scanned_at = scanned_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(scanned_at)
        except Exception:
            return jsonify({"ok": False, "error": "Bad scanned_at format"}), 400
    scanned_date = (dt.date() if dt else date.today())

    # Ensures only one record per student/day or updates if already exists
    record = Attendance.query.filter_by(student_id=student.id, date=scanned_date).first()
    if record:
        record.status = status
    else:
        record = Attendance(student_id=student.id, status=status, date=scanned_date)
        db.session.add(record)

    db.session.commit()
    return jsonify({
        "ok": True,
        "student_id": student.id,
        "date": scanned_date.isoformat(),
        "status": record.status
    }), 201

#  ESP32 + R307 endpoints
@api.post("/biometric/verify")
@limiter.limit("60/minute")
def biometric_verify():
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    finger_id  = data.get("finger_id")
    device_id  = (data.get("device_id") or "R307S").strip()
    confidence = data.get("confidence")  
    status_in  = (data.get("status") or "present").upper()

    # HANDLE FAILED/UNMATCHED FIRST (no student lookup)
    if status_in == "MATCH_FAIL":
        today = date.today()
        att = Attendance(
            student_id=None,
            teacher_id=None,
            date=today,
            status="MATCH_FAIL",
            remarks="unmatched fingerprint",
            source="fingerprint",
            device_id=device_id,
            finger_id=finger_id if isinstance(finger_id, int) else None,
            confidence=confidence if isinstance(confidence, int) else None,
            department=None,
            role="unknown",
            scanned_at=datetime.now(timezone.utc),
        )
        db.session.add(att)
        db.session.commit()

        return jsonify({
            "ok": True,
            "attendance": {
                "date": att.date.isoformat(),
                "status": att.status,
                "source": att.source,
                "device_id": att.device_id,
                "finger_id": att.finger_id,
                "confidence": att.confidence,
                "scanned_at": att.scanned_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        }), 200    

    if not isinstance(student_id, int) or student_id <= 0:
        return jsonify({"ok": False, "error": "Invalid student_id"}), 400
    
    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404

    today = date.today()

    att = Attendance.query.filter_by(student_id=student.id, date=today).first()
    if not att:
        att = Attendance(student_id=student.id, date=today)
        db.session.add(att)

    att.status = "present"
    att.source = "fingerprint"
    att.device_id = device_id
    att.finger_id = finger_id if isinstance(finger_id, int) else att.finger_id
    att.confidence = confidence if isinstance(confidence, int) else att.confidence
    att.scanned_at = datetime.now(timezone.utc)
    att.teacher_id = getattr(student, "teacher_id", None)
    att.department = getattr(student, "department", None)
    att.role = "student"

    db.session.commit()

    return jsonify({
        "ok": True,
        "student": {"id": student.id, "name": student.full_name, "department": student.department},
        "attendance": {
            "date": att.date.isoformat(),
            "status": att.status,
            "source": att.source,
            "device_id": att.device_id,
            "finger_id": att.finger_id,
            "confidence": att.confidence,
            "scanned_at": (
            att.scanned_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if att.scanned_at else None
        ),
        }
    }), 200

@api.post("/biometric/enroll")
@limiter.limit("30/minute")
def biometric_enroll():
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    finger_id  = data.get("finger_id")
    device_id  = (data.get("device_id") or "R307S").strip()

    template_b64 = data.get("template_b64")   # raw R307 template base64 (optional)
    sensor_type  = (data.get("sensor_type") or "R307").strip()
    tpl_version  = (data.get("template_version") or "v1").strip()

    if not (isinstance(student_id, int) and isinstance(finger_id, int)):
        return jsonify({"ok": False, "error": "Invalid student_id/finger_id"}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404

    # Audit entry
    att = Attendance(
        student_id=student_id,
        teacher_id=getattr(student, "teacher_id", None),
        date=date.today(),
        status="present",                # mark attendance on enroll
        remarks="enrolled template",
        source="fingerprint",
        device_id=device_id,
        finger_id=finger_id,
        confidence=100,
        department=student.department,
        role="student",
        scanned_at=datetime.utcnow()
    )
    db.session.add(att)
    db.session.commit()

    # Best-effort secure store (won't break enroll if it fails)
    if isinstance(template_b64, str) and template_b64:
        _save_encrypted_template_safe(
            student_id=student_id,
            finger_id=finger_id,
            device_id=device_id,
            raw_template_b64=template_b64,
            sensor_type=sensor_type,
            template_version=tpl_version
        )

    return jsonify({"ok": True, "student_id": student_id, "finger_id": finger_id}), 201

def _save_encrypted_template_safe(*, student_id: int, finger_id: int, device_id: str,
                                  raw_template_b64: str, sensor_type: str = "R307",
                                  template_version: str = "v1") -> None:
    """
    Best-effort secure store of a fingerprint template.
    Never raises (so it can't break existing enroll flow).
    """
    try:
        if not raw_template_b64:
            return

        # basic sanity: base64 decode to make sure it's valid
        try:
            base64.b64decode(raw_template_b64, validate=True)
        except Exception:
            logging.warning("biotpl: invalid base64, skipping secure store")
            return

        tpl_sha = sha256_hex(raw_template_b64.encode("utf-8"))
        cipher_b64, nonce_b64 = encrypt_template(raw_template_b64)

        # Upsert by (student_id, sensor_type, finger_id)
        existing = BiometricTemplate.query.filter_by(
            student_id=student_id,
            sensor_type=sensor_type,
            finger_id=finger_id
        ).first()

        if existing:
            existing.cipher_b64 = cipher_b64
            existing.nonce_b64 = nonce_b64
            existing.tpl_sha256_hex = tpl_sha
            existing.device_id = device_id or existing.device_id
        else:
            rec = BiometricTemplate(
                student_id=student_id,
                sensor_type=sensor_type,
                template_version=template_version,
                finger_id=finger_id,
                device_id=device_id,
                cipher_b64=cipher_b64,
                nonce_b64=nonce_b64,
                tpl_sha256_hex=tpl_sha,
            )
            db.session.add(rec)

        db.session.commit()
    except Exception as e:
        # Never let this bubble up into your enroll flow.
        db.session.rollback()
        logging.exception("biotpl: secure template save failed: %s", e)

