import os
import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import redis

logger = logging.getLogger(__name__)

router = APIRouter()



REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
from app.core.auth import require_admin


REDIS_STAGING_HOST = os.getenv("REDIS_STAGING_HOST", "whatsapp_ai_redis_staging")
REDIS_STAGING_PORT = int(os.getenv("REDIS_STAGING_PORT", "6379"))

try:
    staging_redis_client = redis.Redis(host=REDIS_STAGING_HOST, port=REDIS_STAGING_PORT, db=0)
except Exception:
    staging_redis_client = None

class AIToggleState(BaseModel):
    enabled: bool

@router.get("/ai-status", response_model=AIToggleState)
def get_ai_status():
    status = redis_client.get("master_ai_enabled")
    if status is None:
        return {"enabled": True}  # Default is ON
    return {"enabled": status.decode("utf-8") == "true"}

@router.post("/ai-status", response_model=AIToggleState)
def set_ai_status(state: AIToggleState):
    status_str = "true" if state.enabled else "false"
    redis_client.set("master_ai_enabled", status_str)
    
    if state.enabled:
        # Re-trigger all pending conversations
        from app.worker.tasks import process_conversation_queue
        import time
        keys = redis_client.keys("convo_queue_*")
        for key in keys:
            conversation_id = key.decode("utf-8").split("_")[-1]
            process_conversation_queue.apply_async(
                args=[int(conversation_id), time.time()]
            )
            
    return {"enabled": state.enabled}


@router.get("/staging/ai-status", response_model=AIToggleState)
def get_staging_ai_status(admin=Depends(require_admin)):
    """Admin-only endpoint to get AI response toggle state for Staging environment."""
    try:
        client = staging_redis_client or redis_client
        status = client.get("master_ai_enabled")
        if status is None:
            return {"enabled": True}
        return {"enabled": status.decode("utf-8") == "true"}
    except Exception as e:
        logger.error(f"Error reading staging Redis: {e}")
        return {"enabled": True}


@router.post("/staging/ai-status", response_model=AIToggleState)
def set_staging_ai_status(state: AIToggleState, admin=Depends(require_admin)):
    """Admin-only endpoint to set AI response toggle state for Staging environment."""
    try:
        client = staging_redis_client or redis_client
        status_str = "true" if state.enabled else "false"
        client.set("master_ai_enabled", status_str)
        return {"enabled": state.enabled}
    except Exception as e:
        logger.error(f"Error updating staging Redis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update staging AI toggle: {e}")


# =========================================================================
# Weekly Business Reporting Admin Configuration & Trigger
# =========================================================================

class ReportingConfigPayload(BaseModel):
    enabled: bool = True
    cron_schedule: str = "0 9 * * 1"
    admin_numbers: list[str] = ["+601165144931", "+14709202239"]
    auto_dispatch_whatsapp: bool = True


@router.get("/reporting-config")
def get_reporting_config(admin=Depends(require_admin)):
    """Admin-only endpoint to retrieve Weekly Business Reporting configuration."""
    raw = redis_client.get("weekly_reporting_config")
    import json
    config = {
        "enabled": True,
        "cron_schedule": "0 9 * * 1 (Mondays at 09:00 MYT)",
        "admin_numbers": ["+601165144931", "+14709202239"],
        "auto_dispatch_whatsapp": True,
        "reports_dir": "/app/data/output/reports",
        "last_generated_at": None,
        "last_status": "Idle"
    }
    if raw:
        try:
            stored = json.loads(raw.decode("utf-8"))
            config.update(stored)
        except Exception:
            pass

    # Check for existing reports
    reports_dir = "/app/data/output/reports"
    buyer_file = None
    owner_file = None
    if os.path.exists(reports_dir):
        for f in sorted(os.listdir(reports_dir), reverse=True):
            if "Buyer_Database" in f and f.endswith(".xlsx") and not buyer_file:
                buyer_file = f
            if "Owner_Database" in f and f.endswith(".xlsx") and not owner_file:
                owner_file = f

    config["latest_buyer_report"] = buyer_file
    config["latest_owner_report"] = owner_file
    return config


@router.post("/reporting-config")
def update_reporting_config(payload: ReportingConfigPayload, admin=Depends(require_admin)):
    """Admin-only endpoint to update Weekly Business Reporting configuration."""
    import json
    data = {
        "enabled": payload.enabled,
        "cron_schedule": payload.cron_schedule,
        "admin_numbers": payload.admin_numbers,
        "auto_dispatch_whatsapp": payload.auto_dispatch_whatsapp,
    }
    redis_client.set("weekly_reporting_config", json.dumps(data))
    return {"status": "success", "config": data}


@router.post("/reporting-trigger")
def trigger_reporting_generation(send_whatsapp: bool = True, admin=Depends(require_admin)):
    """Admin-only endpoint to immediately trigger Weekly Database Report generation and dispatch."""
    from app.services.reporting import WeeklyDatabaseReportManager
    try:
        mgr = WeeklyDatabaseReportManager()
        res = mgr.generate_and_dispatch(send_to_admins=send_whatsapp)
        return {"status": "success", "result": res}
    except Exception as e:
        logger.error(f"Failed to trigger reporting: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reporting-download/{report_type}")
def download_weekly_report(report_type: str, admin=Depends(require_admin)):
    """Admin-only endpoint to download latest generated Excel report ('buyer' or 'owner')."""
    from fastapi.responses import FileResponse
    reports_dir = "/app/data/output/reports"
    if not os.path.exists(reports_dir):
        raise HTTPException(status_code=404, detail="Reports directory does not exist yet.")

    keyword = "Buyer_Database" if report_type.lower() == "buyer" else "Owner_Database"
    matching = [
        f for f in sorted(os.listdir(reports_dir), reverse=True)
        if keyword in f and f.endswith(".xlsx")
    ]
    if not matching:
        raise HTTPException(status_code=404, detail=f"No {report_type} report found. Trigger generation first.")

    target_file = os.path.join(reports_dir, matching[0])
    return FileResponse(
        path=target_file,
        filename=matching[0],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# =========================================================================
# Lead Nurturing & Follow-up Admin Configuration & Trigger
# =========================================================================

class NurturingConfigPayload(BaseModel):
    enabled: bool = True
    staging_acceleration: bool = False
    meta_template_name: str = "lead_reengagement_utility"
    hot_cadence_hours: float = 24.0
    warm_cadence_days: float = 5.0
    cold_cadence_days: float = 14.0


@router.get("/nurturing-config")
def get_nurturing_config(admin=Depends(require_admin)):
    """Admin-only endpoint to inspect current Lead Nurturing engine configuration."""
    raw = redis_client.get("lead_nurturing_config")
    import json
    is_staging = (os.getenv("ENVIRONMENT") or "").lower() == "staging" or os.getenv("STAGING_ACCELERATION_MODE") == "true"
    config = {
        "enabled": True,
        "staging_acceleration": is_staging,
        "meta_template_name": os.getenv("WHATSAPP_REENGAGEMENT_TEMPLATE", "lead_reengagement_utility"),
        "hot_cadence_hours": 24.0,
        "warm_cadence_days": 5.0,
        "cold_cadence_days": 14.0,
        "meta_24h_window_guard": True,
        "cron_schedule": "Hourly (0 * * * *)"
    }
    if raw:
        try:
            stored = json.loads(raw.decode("utf-8"))
            config.update(stored)
        except Exception:
            pass
    return config


@router.post("/nurturing-config")
def update_nurturing_config(payload: NurturingConfigPayload, admin=Depends(require_admin)):
    """Admin-only endpoint to update Lead Nurturing engine cadences."""
    import json
    data = {
        "enabled": payload.enabled,
        "staging_acceleration": payload.staging_acceleration,
        "meta_template_name": payload.meta_template_name,
        "hot_cadence_hours": payload.hot_cadence_hours,
        "warm_cadence_days": payload.warm_cadence_days,
        "cold_cadence_days": payload.cold_cadence_days,
    }
    redis_client.set("lead_nurturing_config", json.dumps(data))
    return {"status": "success", "config": data}


@router.post("/nurturing-trigger")
def trigger_nurturing_cycle(test_phone: Optional[str] = None, force_cadence: Optional[str] = None, admin=Depends(require_admin)):
    """Admin-only endpoint to trigger immediate nurturing evaluation for all leads or a single phone number."""
    from app.services.lead_nurturing import LeadNurturingService
    from app.db.models import SessionLocal, Customer
    try:
        service = LeadNurturingService()
        if test_phone:
            db = SessionLocal()
            try:
                clean_p = test_phone.replace("+", "").replace(" ", "").replace("-", "")
                cust = db.query(Customer).filter((Customer.id == clean_p) | (Customer.id.like(f"%{clean_p}%"))).first()
                if not cust:
                    raise HTTPException(status_code=404, detail=f"Customer with phone '{test_phone}' not found.")
                res = service.evaluate_single_lead(cust, forced_cadence=force_cadence, db=db)
                return {"status": "success", "mode": "single_customer", "result": res}
            finally:
                db.close()
        else:
            res = service.run_cycle()
            return {"status": "success", "mode": "full_cycle", "result": res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger nurturing run: {e}")
        raise HTTPException(status_code=500, detail=str(e))


