from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.db.models import WorkflowTemplate, SessionLocal

router = APIRouter()


class WorkflowStepResponse(BaseModel):
    id: int
    persona_type: str
    step_number: int
    step_name: str
    ai_action_instruction: str
    message_template: str
    expected_data_keys: Optional[List[str]] = []
    next_step: Optional[int] = None

    class Config:
        from_attributes = True


@router.get("/workflows", response_model=List[WorkflowStepResponse])
def get_all_workflows():
    """Return all workflow templates ordered by persona_type then step_number."""
    db = SessionLocal()
    try:
        rows = (
            db.query(WorkflowTemplate)
            .order_by(WorkflowTemplate.persona_type, WorkflowTemplate.step_number)
            .all()
        )
        return rows
    finally:
        db.close()


@router.get("/workflows/{persona_type}", response_model=List[WorkflowStepResponse])
def get_workflows_by_persona(persona_type: str):
    """Return workflow templates for a specific persona type."""
    db = SessionLocal()
    try:
        rows = (
            db.query(WorkflowTemplate)
            .filter(WorkflowTemplate.persona_type == persona_type.upper())
            .order_by(WorkflowTemplate.step_number)
            .all()
        )
        if not rows:
            raise HTTPException(status_code=404, detail=f"No workflows found for persona: {persona_type}")
        return rows
    finally:
        db.close()
