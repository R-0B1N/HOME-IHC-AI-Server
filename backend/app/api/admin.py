from fastapi import APIRouter, HTTPException, Depends
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


class WorkflowStepUpdate(BaseModel):
    step_name: Optional[str] = None
    ai_action_instruction: Optional[str] = None
    message_template: Optional[str] = None
    expected_data_keys: Optional[List[str]] = None
    next_step: Optional[int] = None


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


@router.put("/workflows/{step_id}", response_model=WorkflowStepResponse)
def update_workflow_step(step_id: int, payload: WorkflowStepUpdate):
    """Update a specific workflow step's message template or AI instructions."""
    db = SessionLocal()
    try:
        step = db.query(WorkflowTemplate).filter(WorkflowTemplate.id == step_id).first()
        if not step:
            raise HTTPException(status_code=404, detail="Workflow step not found")

        if payload.step_name is not None:
            step.step_name = payload.step_name.strip()
        if payload.ai_action_instruction is not None:
            step.ai_action_instruction = payload.ai_action_instruction.strip()
        if payload.message_template is not None:
            step.message_template = payload.message_template.strip()
        if payload.expected_data_keys is not None:
            step.expected_data_keys = payload.expected_data_keys
        if payload.next_step is not None:
            step.next_step = payload.next_step

        db.commit()
        db.refresh(step)
        return step
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
