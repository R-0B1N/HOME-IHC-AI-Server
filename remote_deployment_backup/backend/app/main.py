from fastapi import FastAPI
from app.api.webhooks import router as webhooks_router
from app.db.models import Base, engine

# Initialize database
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Real Estate WhatsApp AI CRM Orchestrator",
    description="Backend orchestration replacing n8n to handle async AI tasks and debouncing.",
    version="1.0.0",
)

app.include_router(webhooks_router, prefix="/api/v1/webhooks")

@app.get("/health")
def health_check():
    return {"status": "ok"}
