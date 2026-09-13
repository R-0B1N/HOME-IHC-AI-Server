from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
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
    phone_number: Optional[str] = None
    assigned_locations: List[str] = []
    assigned_property_types: List[str] = []
    is_active: bool
    created_at: Optional[str] = None

class CreateUserByAdminRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None
    role: str = "agent" # "admin", "agent", "employee", "viewer"
    phone_number: Optional[str] = None
    assigned_locations: Optional[List[str]] = []
    assigned_property_types: Optional[List[str]] = []
    is_active: bool = True

class UpdateUserByAdminRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None # "admin", "agent", "employee", "viewer"
    phone_number: Optional[str] = None
    assigned_locations: Optional[List[str]] = None
    assigned_property_types: Optional[List[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

def _serialize_user(u: User) -> dict:
    return {
        "id": str(u.id),
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "phone_number": u.phone_number,
        "assigned_locations": u.assigned_locations or [],
        "assigned_property_types": u.assigned_property_types or [],
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None
    }

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
    return [_serialize_user(u) for u in users]

@router.get("/pending", response_model=List[UserAdminResponse])
def list_pending_users(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all users awaiting administrator activation.
    """
    users = db.query(User).filter(User.is_active == False).order_by(User.created_at.desc()).all()
    return [_serialize_user(u) for u in users]

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
    
    if role not in ["admin", "agent", "employee", "viewer"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be one of: admin, agent, employee, viewer"
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

    clean_phone = data.phone_number.strip() if data.phone_number else None
    if clean_phone == "":
        clean_phone = None
    if clean_phone:
        if db.query(User).filter(User.phone_number == clean_phone).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered to another user"
            )
        
    new_user = User(
        id=uuid.uuid4(),
        username=clean_username,
        email=clean_email,
        hashed_password=get_password_hash(data.password),
        full_name=data.full_name.strip() if data.full_name else clean_username,
        role=role,
        phone_number=clean_phone,
        assigned_locations=data.assigned_locations or [],
        assigned_property_types=data.assigned_property_types or [],
        is_active=data.is_active
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return _serialize_user(new_user)

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
    if user.role == "admin" and (data.role is not None and data.role != "admin" or data.is_active is False):
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
        if clean_role not in ["admin", "agent", "employee", "viewer"]:
            raise HTTPException(status_code=400, detail="Role must be one of: admin, agent, employee, viewer")
        user.role = clean_role
    if data.phone_number is not None:
        clean_phone = data.phone_number.strip() if data.phone_number else None
        if clean_phone == "":
            clean_phone = None
        if clean_phone:
            existing_phone = db.query(User).filter(User.phone_number == clean_phone, User.id != user.id).first()
            if existing_phone:
                raise HTTPException(status_code=400, detail="Phone number already in use by another user")
        user.phone_number = clean_phone
    if data.assigned_locations is not None:
        user.assigned_locations = data.assigned_locations
    if data.assigned_property_types is not None:
        user.assigned_property_types = data.assigned_property_types
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.password:
        user.hashed_password = get_password_hash(data.password)
        
    db.commit()
    db.refresh(user)
    
    return _serialize_user(user)

@router.post("/{user_id}/approve", response_model=UserAdminResponse)
def approve_user_activation(
    user_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Approve and activate a pending user account (1-click approval).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    db.commit()
    db.refresh(user)
    return _serialize_user(user)

@router.post("/{user_id}/reject")
def reject_user_activation(
    user_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Reject and remove a pending user registration.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_active and user.role == "admin":
        raise HTTPException(status_code=400, detail="Cannot reject an active admin account")
    deleted_username = user.username
    db.delete(user)
    db.commit()
    return {"message": f"User @{deleted_username} registration rejected and removed", "id": user_id}

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
