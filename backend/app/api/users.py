from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, ConfigDict
from typing import List, Optional
from app.db.models import SessionLocal, User
from app.core.security import get_password_hash
from app.core.auth import require_admin, get_db
import uuid

router = APIRouter()

class UserAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    email: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[str] = None

class CreateUserByAdminRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: str = "agent" # "admin", "agent", "viewer"
    is_active: bool = True

class UpdateUserByAdminRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None # "admin", "agent", "viewer"
    is_active: Optional[bool] = None
    password: Optional[str] = None

@router.get("", response_model=List[UserAdminResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all registered users (Admin only).
    """
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None
        }
        for u in users
    ]

@router.post("", response_model=UserAdminResponse)
def create_user_admin(
    data: CreateUserByAdminRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Create a new user account with assigned role (Admin only).
    """
    clean_username = data.username.strip().lower()
    clean_email = data.email.strip().lower()
    role = data.role.strip().lower()
    
    if role not in ["admin", "agent", "viewer"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be one of: admin, agent, viewer"
        )
        
    if db.query(User).filter(User.username == clean_username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )
        
    if db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address already registered"
        )
        
    new_user = User(
        id=uuid.uuid4(),
        username=clean_username,
        email=clean_email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name.strip() if data.full_name else clean_username,
        role=role,
        is_active=data.is_active
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
        "is_active": new_user.is_active,
        "created_at": new_user.created_at.isoformat() if new_user.created_at else None
    }

@router.put("/{user_id}", response_model=UserAdminResponse)
def update_user_admin(
    user_id: str,
    data: UpdateUserByAdminRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Update an existing user's role, status, or details (Admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    # Prevent deactivating or demoting the last active admin
    if user.role == "admin" and (data.role != "admin" or data.is_active is False):
        active_admins = db.query(User).filter(User.role == "admin", User.is_active == True).count()
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote or deactivate the only remaining active admin"
            )
            
    if data.full_name is not None:
        user.full_name = data.full_name.strip()
    if data.email is not None:
        clean_email = data.email.strip().lower()
        existing = db.query(User).filter(User.email == clean_email, User.id != user.id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use by another account")
        user.email = clean_email
    if data.role is not None:
        clean_role = data.role.strip().lower()
        if clean_role not in ["admin", "agent", "viewer"]:
            raise HTTPException(status_code=400, detail="Role must be one of: admin, agent, viewer")
        user.role = clean_role
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = get_password_hash(data.password)
        
    db.commit()
    db.refresh(user)
    
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None
    }

@router.delete("/{user_id}")
def delete_user_admin(
    user_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Delete a user account (Admin only).
    """
    if str(current_admin.id) == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own admin account"
        )
        
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    if user.role == "admin":
        active_admins = db.query(User).filter(User.role == "admin").count()
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the only remaining admin"
            )
            
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully", "id": user_id}
