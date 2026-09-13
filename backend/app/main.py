import os
import uuid
import datetime
import logging
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
from app.api.transcripts import router as transcripts_router
from app.api.acknowledgements import router as acknowledgements_router
from app.db.models import Base, engine, SessionLocal, User, WorkflowTemplate, Customer, Property, run_schema_migrations
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)

# Initialize database schema and run pgvector migrations
try:
    Base.metadata.create_all(bind=engine)
    run_schema_migrations(engine)
except Exception as e:
    logger.warning(f"Database schema initialization warning: {e}")

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
            default_admin_pass = os.getenv("ADMIN_DEFAULT_PASSWORD")
            if not default_admin_pass:
                logger.error("ADMIN_DEFAULT_PASSWORD environment variable is required!")
                raise ValueError("ADMIN_DEFAULT_PASSWORD must be configured in environment variables")
            
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
                
        # 2. Ensure Workflow templates exist and are kept up to date
        from scripts.seed_workflows import seed_workflows
        seed_workflows()

        # 3. Purge dummy/mock properties so only authentic WordPress listings remain
        from scripts.seed_properties import purge_dummy_properties
        purge_dummy_properties()

        # 4. Ensure Customer leads are synced from Chatwoot
        cust_count = db.query(Customer).count()
        if cust_count == 0:
            print("👥 Auto-syncing initial leads from Chatwoot...")
            from app.services.chatwoot import get_all_contacts
            try:
                for p in range(1, 4):
                    contacts = get_all_contacts(page=p)
                    if not contacts: break
                    for contact in contacts:
                        phone = contact.get("phone_number") or contact.get("identifier")
                        if not phone: continue
                        if not db.query(Customer).filter(Customer.id == phone).first():
                            db.add(Customer(
                                id=phone,
                                contact_name=contact.get("name") or "WhatsApp Lead",
                                email=contact.get("email"),
                                country="Malaysia",
                                last_interaction=datetime.datetime.utcnow(),
                                metadata_json={"chatwoot_contact_id": contact.get("id"), "source": "chatwoot_startup_sync"}
                            ))
                db.commit()
            except Exception as sync_err:
                print(f"Chatwoot auto-sync notice: {sync_err}")
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
app.include_router(wordpress_router, prefix="/api/v1/wordpress", tags=["WordPress"])
app.include_router(wordpress_router, prefix="/api/v1/webhooks/wordpress", tags=["WordPress Webhook"])
app.include_router(properties_router, prefix="/api/v1/properties", tags=["Properties"])
app.include_router(customers_router, prefix="/api/v1/customers", tags=["Customers & Leads"])
app.include_router(settings_router, prefix="/api/v1/settings", tags=["Settings"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["Workflows & Admin"])
app.include_router(transcripts_router)
app.include_router(acknowledgements_router, prefix="/api/v1/acknowledgements", tags=["Viewing Acknowledgements"])

@app.get("/health")
def health_check():
    return {"status": "ok"}

