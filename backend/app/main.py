from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.webhooks import router as webhooks_router
from app.api.properties import router as properties_router
from app.api.customers import router as customers_router
from app.api.wordpress import router as wordpress_router
from app.db.models import Base, engine

# Initialize database and run auto-migration if needed
try:
    import scripts.migrate_properties_to_uuid as migrator
    migrator.migrate()
except Exception as e:
    print(f"Auto-migration skipped or failed: {e}")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Real Estate WhatsApp AI CRM Orchestrator",
    description="Backend orchestration replacing n8n to handle async AI tasks and debouncing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhooks_router, prefix="/api/v1/webhooks")
app.include_router(webhooks_router, prefix="/webhook") # Fallback for old n8n webhook URL
app.include_router(wordpress_router, prefix="/api/v1/webhooks/wordpress")
app.include_router(properties_router, prefix="/api/v1/properties")
app.include_router(customers_router, prefix="/api/v1/customers")

@app.get("/health")
def health_check():
    return {"status": "ok"}
