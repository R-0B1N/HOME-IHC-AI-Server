from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, Dict, Any
from app.db.models import SessionLocal, User
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.auth import get_current_user
import uuid

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class LoginRequest(BaseModel):
    username_or_email: str
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    phone_number: Optional[str] = None
    assigned_locations: Optional[list] = None
    assigned_property_types: Optional[list] = None
    is_active: bool

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None
    role: Optional[str] = "agent" # "admin", "agent", "employee", "viewer"
    phone_number: Optional[str] = None
    assigned_locations: Optional[list] = None
    assigned_property_types: Optional[list] = None

@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate a user with username/email and password, returning a JWT token.
    """
    query = credentials.username_or_email.strip()
    user = (
        db.query(User)
        .filter((User.username == query) | (User.email == query))
        .first()
    )
    
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has not been activated or has been deactivated. Please contact an administrator."
        )
        
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role
        }
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "phone_number": user.phone_number,
            "full_name": user.full_name,
            "role": user.role,
            "assigned_locations": user.assigned_locations or [],
            "assigned_property_types": user.assigned_property_types or [],
            "is_active": user.is_active
        }
    }

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Retrieve information about the currently authenticated user.
    """
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "phone_number": current_user.phone_number,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "assigned_locations": current_user.assigned_locations or [],
        "assigned_property_types": current_user.assigned_property_types or [],
        "is_active": current_user.is_active
    }

@router.post("/register", response_model=UserResponse)
def register_account(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user account with a specified role.
    If no user exists in the system yet, the first registered user is automatically made an active admin.
    Otherwise, newly registered accounts are set to is_active=False pending admin approval.
    """
    clean_username = data.username.strip().lower()
    clean_email = data.email.strip().lower()
    clean_phone = data.phone_number.strip() if (data.phone_number and data.phone_number.strip()) else None
    
    # Check if username exists
    if db.query(User).filter(User.username == clean_username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
        
    # Check if email exists
    if db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered"
        )

    # Check if phone number exists if provided
    if clean_phone:
        if db.query(User).filter(User.phone_number == clean_phone).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered with another account"
            )
        
    # Check total user count - if 0, bootstrap to active admin
    total_users = db.query(User).count()
    if total_users == 0:
        assigned_role = "admin"
        is_active_status = True
    else:
        assigned_role = (data.role or "agent").lower()
        if assigned_role not in ["admin", "agent", "employee", "viewer"]:
            assigned_role = "agent"
        is_active_status = False  # New registrations require admin activation
        
    new_user = User(
        id=uuid.uuid4(),
        username=clean_username,
        email=clean_email,
        phone_number=clean_phone,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name.strip() if data.full_name else clean_username,
        role=assigned_role,
        assigned_locations=data.assigned_locations or [],
        assigned_property_types=data.assigned_property_types or [],
        is_active=is_active_status
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "id": str(new_user.id),
        "username": new_user.username,
        "email": new_user.email,
        "phone_number": new_user.phone_number,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "assigned_locations": new_user.assigned_locations or [],
        "assigned_property_types": new_user.assigned_property_types or [],
        "is_active": new_user.is_active
    }
