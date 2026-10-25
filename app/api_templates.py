import base64, hashlib, os
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timezone
from app.models import db, Student, BiometricTemplate
from app.utils.biocrypt import BioCrypt
from app.api import require_api_key

api_tpl = Blueprint("api_tpl", __name__, url_prefix="/api/biometric/template")

def _biocrypt():
    return BioCrypt(os.getenv("BIOCRYPT_KEY"))

def _b64_to_bytes(s: str) -> bytes:
    return base64.b64decode(s) if s else b""

@api_tpl.post("/upload")
def upload_template():
    # Gate behind API key or admin session — your choice:
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    template_b64 = data.get("template_b64")  # raw device template, base64
    sensor_type = (data.get("sensor_type") or "R307").strip()
    template_version = (data.get("template_version") or "v1").strip()
    device_id = (data.get("device_id") or "").strip()
    finger_id = data.get("finger_id")

    if not isinstance(student_id, int) or student_id <= 0:
        return jsonify({"ok": False, "error": "Invalid student_id"}), 400
    if not template_b64:
        return jsonify({"ok": False, "error": "template_b64 required"}), 400

    student = Student.query.get(student_id)
    if not student:
        return jsonify({"ok": False, "error": "Student not found"}), 404

    raw_tpl = _b64_to_bytes(template_b64)
    sha_hex = hashlib.sha256(raw_tpl).hexdigest()

    # encrypt template (AAD ties it to student & type for context-binding)
    aad = f"{student_id}|{sensor_type}|{template_version}".encode()
    enc = _biocrypt().encrypt(raw_tpl, aad=aad)

    rec = BiometricTemplate(
        student_id=student_id,
        sensor_type=sensor_type,
        template_version=template_version,
        finger_id=finger_id if isinstance(finger_id, int) else None,
        device_id=device_id or None,
        cipher_b64=enc["cipher_b64"],
        nonce_b64=enc["nonce_b64"],
        tpl_sha256_hex=sha_hex,
    )
    db.session.add(rec)
    db.session.commit()

    return jsonify({"ok": True, "template_id": rec.id, "hash": sha_hex})

def _iso_utc(dt):
    if not dt:
        return None
    # Coerce naive -> UTC, keep aware -> convert to UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

@api_tpl.get("/list")
def list_templates():
    # allow admin UI to inspect; still keep API key gate to be safe.
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    student_id = request.args.get("student_id", type=int)
    q = BiometricTemplate.query
    if student_id:
        q = q.filter(BiometricTemplate.student_id == student_id)
    rows = q.order_by(BiometricTemplate.created_at.desc()).limit(100).all()
    return jsonify({
        "ok": True,
        "items": [{
            "id": r.id,
            "student_id": r.student_id,
            "sensor_type": r.sensor_type,
            "template_version": r.template_version,
            "finger_id": r.finger_id,
            "device_id": r.device_id,
            "hash": r.tpl_sha256_hex,
            "created_at": _iso_utc(r.created_at),
        } for r in rows]
    })
