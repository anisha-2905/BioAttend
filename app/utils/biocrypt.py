# app/utils/biocrypt.py
import base64, os, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class BioCrypt:
    def __init__(self, key_b64: str):
        if not key_b64:
            raise RuntimeError("BIOCRYPT_KEY missing")
        self._key = base64.b64decode(key_b64)

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> dict:
        aes = AESGCM(self._key)
        nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
        ct = aes.encrypt(nonce, plaintext, aad)
        return {
            "nonce_b64": base64.b64encode(nonce).decode(),
            "cipher_b64": base64.b64encode(ct).decode(),
        }

    def decrypt(self, cipher_b64: str, nonce_b64: str, aad: bytes = b"") -> bytes:
        aes = AESGCM(self._key)
        nonce = base64.b64decode(nonce_b64)
        ct = base64.b64decode(cipher_b64)
        return aes.decrypt(nonce, ct, aad)

# lazy singleton
_biocrypt_instance = None

def _get_key_b64():
    # supports either name: preferring BIO_KEY if present
    return os.getenv("BIO_KEY") or os.getenv("BIOCRYPT_KEY")

def _bc() -> BioCrypt:
    global _biocrypt_instance
    if _biocrypt_instance is None:
        key_b64 = _get_key_b64()
        if not key_b64:
            raise RuntimeError("BIO_KEY/BIOCRYPT_KEY not set in environment")
        _biocrypt_instance = BioCrypt(key_b64)
    return _biocrypt_instance

def encrypt_template(plain_b64: str):
    """
    Accepts a base64 string (finger template) and returns (cipher_b64, nonce_b64).
    Matches the interface used in api.py.
    """
    if not plain_b64:
        raise ValueError("empty template")
    out = _bc().encrypt(plain_b64.encode("utf-8"))
    return out["cipher_b64"], out["nonce_b64"]

def decrypt_template(cipher_b64: str, nonce_b64: str) -> str:
    """
    For completeness: returns the original base64 string.
    """
    return _bc().decrypt(cipher_b64, nonce_b64).decode("utf-8")

def sha256_hex(data) -> str:
    """
    SHA-256 hex digest; accepts bytes or str.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
