"""Admin endpoints for the on-server recategorization job."""

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import List, Optional

from app.core.auth import require_admin, security_scheme
from app.core.security import generate_report_download_token, verify_report_download_token
from app.services.recategorize_service import SqlJobStore

router = APIRouter()


class StartJob(BaseModel):
    mode: str = "dry_run"
    limit: Optional[int] = None
    conversation_id: Optional[str] = None
    rate: float = 1.0
    resume: bool = False
    batch_id: Optional[str] = None


class ApplyJob(BaseModel):
    accepted_conversation_ids: List[str] = Field(default_factory=list)


def _store():
    return SqlJobStore()


def _enqueue(batch_id: str, accepted=None):
    from app.worker.tasks import run_recategorize_job
    run_recategorize_job.apply_async(
        args=[batch_id],
        kwargs={"accepted_conversation_ids": accepted},
        queue="recategorize",
    )


@router.post("/jobs")
def start_job(body: StartJob, admin=Depends(require_admin)):
    """Queue a dry_run (default), or record an apply/rollback to be run by the worker."""
    mode = (body.mode or "dry_run").strip().lower()
    if mode not in {"dry_run", "apply", "rollback"}:
        raise HTTPException(status_code=400, detail="mode must be dry_run, apply, or rollback")
    if body.rate <= 0 or body.rate > 1:
        raise HTTPException(status_code=400, detail="rate must be greater than 0 and at most 1 request per second")
    store = _store()
    if mode == "dry_run":
        job = store.create_job(
            batch_id=body.batch_id,
            mode="dry_run",
            rate=body.rate,
            conversation_limit=body.limit,
            conversation_id=body.conversation_id,
            checkpoint_json=[] if not body.resume else None,
        )
        if body.resume and body.batch_id:
            existing = store.get_job(body.batch_id)
            job = existing or job
        _enqueue(job["batch_id"])
        return job
    if not body.batch_id:
        raise HTTPException(status_code=400, detail="batch_id is required for apply and rollback")
    existing = store.get_job(body.batch_id)
    if not existing:
        raise HTTPException(status_code=404, detail="batch not found")
    store.update_job(body.batch_id, mode=mode, status="queued")
    _enqueue(body.batch_id)
    return store.get_job(body.batch_id)


@router.get("/jobs/{batch_id}")
def job_status(batch_id: str, admin=Depends(require_admin)):
    job = _store().get_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    return job


@router.post("/jobs/{batch_id}/apply")
def apply_job(batch_id: str, body: ApplyJob, admin=Depends(require_admin)):
    if not body.accepted_conversation_ids:
        raise HTTPException(status_code=400, detail="accepted_conversation_ids is required")
    store = _store()
    job = store.get_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    store.update_job(
        batch_id,
        mode="apply",
        status="queued",
        accepted_ids=[str(item) for item in body.accepted_conversation_ids],
    )
    _enqueue(batch_id, accepted=[str(item) for item in body.accepted_conversation_ids])
    return store.get_job(batch_id)


@router.post("/jobs/{batch_id}/rollback")
def rollback_job(batch_id: str, admin=Depends(require_admin)):
    store = _store()
    if not store.get_job(batch_id):
        raise HTTPException(status_code=404, detail="batch not found")
    store.update_job(batch_id, mode="rollback", status="queued")
    _enqueue(batch_id)
    return store.get_job(batch_id)


def _authorized_download(batch_id: str, token: Optional[str], credentials: Optional[HTTPAuthorizationCredentials]) -> bool:
    if token and verify_report_download_token("recategorize", batch_id, token):
        return True
    if credentials:
        from app.core.auth import get_current_user, get_db
        # Direct check is performed by the route via require_admin when no token is present.
        return False
    return False


@router.get("/jobs/{batch_id}/download")
def download_job(
    batch_id: str,
    fmt: str = Query("csv", alias="format"),
    token: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
):
    """
    Admin JWT, or the same HMAC pattern as the weekly report:
    ``?token=`` from ``generate_report_download_token('recategorize', batch_id)``.
    """
    allowed = bool(token) and verify_report_download_token("recategorize", batch_id, token)
    if not allowed:
        if not credentials:
            raise HTTPException(status_code=401, detail="Authentication credentials or a valid report token required")
        from app.core.auth import get_current_user
        from app.db.models import SessionLocal
        db = SessionLocal()
        try:
            user = get_current_user(credentials, db)
        finally:
            db.close()
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Administrative privileges required")
    job = _store().get_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    path = job["output_xlsx"] if fmt.lower() in {"xlsx", "excel"} else job["output_csv"]
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="report file is not ready")
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if path.endswith(".xlsx")
        else "text/csv"
    )
    return FileResponse(path=path, filename=os.path.basename(path), media_type=media)


@router.get("/jobs/{batch_id}/download-token")
def download_token(batch_id: str, admin=Depends(require_admin)):
    return {
        "batch_id": batch_id,
        "token": generate_report_download_token("recategorize", batch_id),
    }
