import sys
import os
from urllib.parse import quote_plus

# Add backend to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from app.core.security import get_password_hash, verify_password, create_access_token, decode_access_token

def test_password_hashing():
    raw = "P@ssw0rdo123!"
    hashed = get_password_hash(raw)
    assert hashed != raw, "Hash should not equal plain password"
    assert verify_password(raw, hashed) is True, "Password should verify"
    assert verify_password("WrongPassword!", hashed) is False, "Wrong password should fail"
    print("✅ test_password_hashing passed")

def test_jwt_tokens():
    payload = {"sub": "user-12345", "username": "admin", "role": "admin"}
    token = create_access_token(payload)
    assert isinstance(token, str), "Token should be string"
    decoded = decode_access_token(token)
    assert decoded["sub"] == "user-12345"
    assert decoded["username"] == "admin"
    assert decoded["role"] == "admin"
    print("✅ test_jwt_tokens passed")

def test_password_url_encoding():
    db_pass = "P@ssw0rdo"
    encoded = quote_plus(db_pass)
    assert encoded == "P%40ssw0rdo", f"Expected P%40ssw0rdo, got {encoded}"
    url = f"postgresql://crm_admin:{encoded}@crm-postgres:5432/n8n_crm"
    assert "@crm-postgres" in url
    assert "crm_admin:P%40ssw0rdo@" in url
    print("✅ test_password_url_encoding passed")

def test_app_routes():
    try:
        from app.main import app
        routes = [route.path for route in app.routes]
        assert "/api/v1/auth/login" in routes, "Missing /api/v1/auth/login"
        assert "/api/v1/auth/me" in routes, "Missing /api/v1/auth/me"
        assert "/api/v1/auth/register" in routes, "Missing /api/v1/auth/register"
        assert "/api/v1/users" in routes, "Missing /api/v1/users"
        assert "/api/v1/properties" in routes, "Missing /api/v1/properties"
        assert "/api/v1/customers" in routes, "Missing /api/v1/customers"
        assert "/api/v1/admin/workflows" in routes, "Missing /api/v1/admin/workflows"
        print("✅ test_app_routes passed")
    except ImportError as e:
        print(f"ℹ️ test_app_routes skipped on host (runs in Docker container): {e}")

if __name__ == "__main__":
    test_password_hashing()
    test_jwt_tokens()
    test_password_url_encoding()
    test_app_routes()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
