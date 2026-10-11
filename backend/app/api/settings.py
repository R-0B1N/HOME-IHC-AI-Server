from __future__ import annotations
import os
import logging
from typing import Optional, Dict, Any, List
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

_IN_MEMORY_SETTINGS = {
    "master_ai_enabled": True,
    "lead_nurturing_enabled": True
}

def get_redis_client_for_env(env: Optional[str] = None):
    if env and env.lower() == "staging" and staging_redis_client:
        return staging_redis_client
    return redis_client

def get_system_toggle(key: str, default: bool = True, env: Optional[str] = None) -> bool:
    """Reads system toggle boolean with fallback to in-memory state on connection error."""
    try:
        client = get_redis_client_for_env(env)
        val = client.get(key)
        if val is not None:
            res = val.decode("utf-8").strip().lower() in ("true", "1", "yes")
            _IN_MEMORY_SETTINGS[key] = res
            return res
    except Exception as e:
        logger.warning(f"Error accessing Redis for toggle '{key}': {e}. Using fallback.")
    return _IN_MEMORY_SETTINGS.get(key, default)

def set_system_toggle(key: str, enabled: bool, env: Optional[str] = None) -> bool:
    """Sets system toggle boolean with in-memory persistence and Redis propagation."""
    _IN_MEMORY_SETTINGS[key] = enabled
    status_str = "true" if enabled else "false"
    try:
        client = get_redis_client_for_env(env)
        client.set(key, status_str)
        return True
    except Exception as e:
        logger.warning(f"Error persisting toggle '{key}' to Redis: {e}.")
        return False

class AIToggleState(BaseModel):
    enabled: bool

@router.get("/ai-status", response_model=AIToggleState)
def get_ai_status(environment: Optional[str] = None):
    enabled = get_system_toggle("master_ai_enabled", default=True, env=environment)
    return {"enabled": enabled}

@router.post("/ai-status", response_model=AIToggleState)
def set_ai_status(state: AIToggleState, environment: Optional[str] = None):
    set_system_toggle("master_ai_enabled", state.enabled, env=environment)
    
    if state.enabled:
        # Re-trigger all pending conversations
        try:
            from app.worker.tasks import process_conversation_queue
            import time
            client = get_redis_client_for_env(environment)
            keys = client.keys("convo_queue_*")
            for key in keys:
                conversation_id = key.decode("utf-8").split("_")[-1]
                process_conversation_queue.apply_async(
                    args=[int(conversation_id), time.time()]
                )
        except Exception as e:
            logger.warning(f"Could not re-trigger queued conversations: {e}")
            
    return {"enabled": state.enabled}


@router.get("/staging/ai-status", response_model=AIToggleState)
def get_staging_ai_status(admin=Depends(require_admin)):
    """Admin-only endpoint to get AI response toggle state for Staging environment."""
    enabled = get_system_toggle("master_ai_enabled", default=True, env="staging")
    return {"enabled": enabled}


@router.post("/staging/ai-status", response_model=AIToggleState)
def set_staging_ai_status(state: AIToggleState, admin=Depends(require_admin)):
    """Admin-only endpoint to set AI response toggle state for Staging environment."""
    set_system_toggle("master_ai_enabled", state.enabled, env="staging")
    return {"enabled": state.enabled}


@router.get("/followup-status", response_model=AIToggleState)
def get_followup_status(environment: Optional[str] = None):
    """Retrieves current Lead Follow-up / Nurturing engine toggle state."""
    enabled = get_system_toggle("lead_nurturing_enabled", default=True, env=environment)
    return {"enabled": enabled}


@router.post("/followup-status", response_model=AIToggleState)
def set_followup_status(state: AIToggleState, environment: Optional[str] = None):
    """Toggles Lead Follow-up / Nurturing engine state in real time and synchronizes config."""
    set_system_toggle("lead_nurturing_enabled", state.enabled, env=environment)
    
    # Also update enabled inside lead_nurturing_config JSON for complete synchronization
    try:
        import json
        client = get_redis_client_for_env(environment)
        raw = client.get("lead_nurturing_config")
        config = {}
        if raw:
            try:
                config = json.loads(raw.decode("utf-8"))
            except Exception:
                config = {}
        config["enabled"] = state.enabled
        client.set("lead_nurturing_config", json.dumps(config))
    except Exception as e:
        logger.warning(f"Could not synchronize lead_nurturing_config JSON: {e}")
        
    return {"enabled": state.enabled}


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
    from app.services.reporting import DEFAULT_REPORTS_DIR, WeeklyDatabaseReportManager
    
    reports_dir = DEFAULT_REPORTS_DIR
    os.makedirs(reports_dir, exist_ok=True)

    keyword = "Buyer_Database" if report_type.lower() == "buyer" else "Owner_Database"
    matching = [
        f for f in sorted(os.listdir(reports_dir), reverse=True)
        if keyword in f and f.endswith(".xlsx")
    ]
    # If no report has been generated yet, automatically generate it on-the-fly!
    if not matching:
        logger.info(f"Report for {report_type} not found in {reports_dir}. Triggering on-demand generation...")
        try:
            mgr = WeeklyDatabaseReportManager(output_dir=reports_dir)
            mgr.generate_all()
            matching = [
                f for f in sorted(os.listdir(reports_dir), reverse=True)
                if keyword in f and f.endswith(".xlsx")
            ]
        except Exception as gen_err:
            logger.error(f"Failed to generate report on the fly: {gen_err}")

    if not matching:
        raise HTTPException(status_code=404, detail=f"No {report_type} report could be generated.")

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
    meta_template_language: str = "en_US"
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
        "meta_template_language": os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "en_US"),
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
    """Admin-only endpoint to update Lead Nurturing engine cadences and template settings."""
    import json
    data = {
        "enabled": payload.enabled,
        "staging_acceleration": payload.staging_acceleration,
        "meta_template_name": payload.meta_template_name,
        "meta_template_language": payload.meta_template_language,
        "hot_cadence_hours": payload.hot_cadence_hours,
        "warm_cadence_days": payload.warm_cadence_days,
        "cold_cadence_days": payload.cold_cadence_days,
    }
    set_system_toggle("lead_nurturing_enabled", payload.enabled)
    try:
        redis_client.set("lead_nurturing_config", json.dumps(data))
    except Exception as e:
        logger.warning(f"Could not save lead_nurturing_config to Redis: {e}")
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


