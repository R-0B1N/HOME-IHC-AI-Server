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
    is_active: bool

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: Optional[str] = "agent" # "admin", "agent", "viewer"

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
            detail="This account has been deactivated. Please contact an administrator."
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
            "full_name": user.full_name,
            "role": user.role,
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
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active
    }

@router.post("/register", response_model=UserResponse)
def register_account(data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user account with a specified role.
    If no admin exists in the system yet, the first registered user is automatically made an admin.
    """
    clean_username = data.username.strip().lower()
    clean_email = data.email.strip().lower()
    
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
        
    # Check total user count - if 0, promote to admin
    total_users = db.query(User).count()
    assigned_role = "admin" if total_users == 0 else (data.role or "agent").lower()
    
    if assigned_role not in ["admin", "agent", "viewer"]:
        assigned_role = "agent"
        
    new_user = User(
        id=uuid.uuid4(),
        username=clean_username,
        email=clean_email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name.strip() if data.full_name else clean_username,
        role=assigned_role,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {
        "id": str(new_user.id),
        "username": new_user.username,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "is_active": new_user.is_active
    }
