import os
import uuid
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.api.webhooks import router as webhooks_router
from app.api.properties import router as properties_router
from app.api.customers import router as customers_router
from app.api.wordpress import router as wordpress_router
from app.api.settings import router as settings_router
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.db.models import Base, engine, SessionLocal, User, WorkflowTemplate
from app.core.security import get_password_hash

# Initialize database and run auto-migration if needed
try:
    import scripts.migrate_properties_to_uuid as migrator
    migrator.migrate()
except Exception as e:
    print(f"Auto-migration skipped or failed: {e}")

try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Database schema initialization warning: {e}")

app = FastAPI(
    title="Real Estate WhatsApp AI CRM Orchestrator",
    description="Backend orchestration handling Real Estate AI, CRM, Workflows, and RBAC Database Access.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """
    Ensure essential tables, default admin user, and initial workflow templates exist.
    """
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Startup table creation notice: {e}")

    db = SessionLocal()
    try:
        # 1. Ensure at least one Admin account exists
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count == 0:
            default_admin_username = os.getenv("ADMIN_DEFAULT_USER", "admin")
            default_admin_email = os.getenv("ADMIN_DEFAULT_EMAIL", "admin@bentongland.com.my")
            default_admin_pass = os.getenv("ADMIN_DEFAULT_PASSWORD", "Admin12345!")
            
            existing = db.query(User).filter((User.username == default_admin_username) | (User.email == default_admin_email)).first()
            if not existing:
                new_admin = User(
                    id=uuid.uuid4(),
                    username=default_admin_username,
                    email=default_admin_email,
                    hashed_password=get_password_hash(default_admin_pass),
                    full_name="System Administrator",
                    role="admin",
                    is_active=True
                )
                db.add(new_admin)
                db.commit()
                print(f"✅ Created default Admin account: {default_admin_username} ({default_admin_email})")
                
        # 2. Ensure Workflow templates exist
        workflow_count = db.query(WorkflowTemplate).count()
        if workflow_count == 0:
            print("🚀 Initializing default workflow templates...")
            from scripts.seed_workflows import seed_workflows
            seed_workflows()
    except Exception as e:
        print(f"Startup initialization error: {e}")
        db.rollback()
    finally:
        db.close()

# Register API Routers
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/api/v1/users", tags=["User Management"])
app.include_router(webhooks_router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(webhooks_router, prefix="/webhook", tags=["Legacy Webhook"]) # Fallback for old n8n webhook URL
app.include_router(wordpress_router, prefix="/api/v1/webhooks/wordpress", tags=["WordPress"])
app.include_router(properties_router, prefix="/api/v1/properties", tags=["Properties"])
app.include_router(customers_router, prefix="/api/v1/customers", tags=["Customers & Leads"])
app.include_router(settings_router, prefix="/api/v1/settings", tags=["Settings"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["Workflows & Admin"])

@app.get("/health")
def health_check():
    return {"status": "ok"}
