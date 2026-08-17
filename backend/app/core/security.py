import os
import hmac
import json
import base64
import hashlib
import secrets
import datetime
from typing import Optional, Union, Any

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "real-estate-crm-ai-secret-key-super-secure-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def _base64url_decode(data_str: str) -> bytes:
    padding = '=' * (4 - (len(data_str) % 4)) if len(data_str) % 4 != 0 else ''
    return base64.urlsafe_b64decode(data_str + padding)

def get_password_hash(password: str) -> str:
    """
    Hash a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and a random salt.
    Format: pbkdf2_sha256$iterations$salt$hash
    """
    salt = secrets.token_hex(16)
    iterations = 100000
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations
    )
    return f"pbkdf2_sha256${iterations}${salt}${key.hex()}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against the stored hash.
    Supports pbkdf2_sha256 and bcrypt if passlib is installed.
    """
    if not hashed_password or not plain_password:
        return False
        
    if hashed_password.startswith("pbkdf2_sha256$"):
        parts = hashed_password.split("$")
        if len(parts) != 4:
            return False
        _, iter_str, salt, stored_hash = parts
        try:
            iterations = int(iter_str)
            calculated_key = hashlib.pbkdf2_hmac(
                'sha256',
                plain_password.encode('utf-8'),
                salt.encode('utf-8'),
                iterations
            ).hex()
            return secrets.compare_digest(calculated_key, stored_hash)
        except Exception:
            return False
            
    # Fallback for bcrypt hashes if passlib is present
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """
    Create a signed JWT access token conforming to RFC 7519 (HS256).
    """
    try:
        import jwt
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.datetime.utcnow() + expires_delta
        else:
            expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": int(expire.timestamp()), "iat": int(datetime.datetime.utcnow().timestamp())})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    except ImportError:
        # Robust pure-Python HS256 JWT implementation
        header = {"alg": "HS256", "typ": "JWT"}
        if expires_delta:
            expire = datetime.datetime.utcnow() + expires_delta
        else:
            expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            
        payload = data.copy()
        payload["exp"] = int(expire.timestamp())
        payload["iat"] = int(datetime.datetime.utcnow().timestamp())
        
        encoded_header = _base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
        encoded_payload = _base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
        
        signing_input = f"{encoded_header}.{encoded_payload}".encode('utf-8')
        signature = hmac.new(SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
        encoded_signature = _base64url_encode(signature)
        
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and validate a signed JWT access token.
    """
    try:
        import jwt
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ImportError:
        # Robust pure-Python HS256 JWT verification
        try:
            parts = token.split('.')
            if len(parts) != 3:
                return None
            encoded_header, encoded_payload, encoded_signature = parts
            
            signing_input = f"{encoded_header}.{encoded_payload}".encode('utf-8')
            expected_sig = hmac.new(SECRET_KEY.encode('utf-8'), signing_input, hashlib.sha256).digest()
            actual_sig = _base64url_decode(encoded_signature)
            
            if not secrets.compare_digest(expected_sig, actual_sig):
                return None
                
            payload_bytes = _base64url_decode(encoded_payload)
            payload = json.loads(payload_bytes.decode('utf-8'))
            
            # Check expiration
            exp = payload.get("exp")
            if exp and datetime.datetime.utcnow().timestamp() > exp:
                return None
                
            return payload
        except Exception:
            return None
    except Exception:
        return None
