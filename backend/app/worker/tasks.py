import logging
import json
import time
import datetime
import os
import redis
import requests
import base64
import uuid
from app.worker.celery_app import celery_app
from app.services.chatwoot import (
    send_message,
    apply_label,
    set_priority,
    toggle_typing_status,
    get_conversation_messages,
    get_or_create_contact,
    create_conversation,
    assign_agent,
    send_chatwoot_image_attachment,
    get_agent_id_by_email,
    CHATWOOT_ACCOUNT_ID,
    send_private_note,
    send_whatsapp_contact,
    send_whatsapp_template,
    update_conversation_status,
)
from app.services.llm import generate_response, transcribe_audio, extract_property_search_criteria, extract_valuer_data, extract_wordpress_property
from app.services.system_prompts import is_handover_promised
from app.services.document_parser import extract_text_from_document
from app.services.db_services import get_or_create_customer, get_sender_role, search_properties, get_active_agents_and_employees
from app.services.session_manager import SessionManager
from app.services.minio_service import upload_media
from app.db.models import SessionLocal, Customer, Property, Transaction, Order, InteractionLog, User


logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

TIMEOUT_SECONDS = 10

from app.services.lead_handover import (
    AgentSpecializationScorer,
    LeadHandoverService,
    CONFIGURED_LOCATIONS,
    CONFIGURED_PROPERTY_TYPES,
    DEFAULT_FALLBACK_ADMIN_NUMBERS,
)

_default_scorer = AgentSpecializationScorer()


def calculate_agent_specialization_score(
    agent,
    lead_location_or_data=None,
    lead_property_type: str = "",
    raw_inquiry_text: str = ""
) -> int:
    """
    Scores an agent based on how many lead criteria match their assigned_locations
    and assigned_property_types.
    Delegates to AgentSpecializationScorer OOP strategy.
    """
    return _default_scorer.calculate_score(
        agent=agent,
        lead_location_or_data=lead_location_or_data,
        lead_property_type=lead_property_type,
        raw_inquiry_text=raw_inquiry_text,
    )


def dispatch_hot_lead_handover(
    conversation_id_or_data=None,
    customer_name: str = "",
    customer_phone: str = "",
    intent: str = "BUYER",
    location: str = "",
    property_type: str = "",
    budget: str = "",
    conversation_summary: str = "",
    cw_link: str = "",
    inbox_id: int = 3,
    raw_inquiry_text: str = "",
    db: SessionLocal = None
) -> dict:
    """
    Dynamic Hot Lead Handover routing based on agent specialization.
    Delegates to LeadHandoverService domain service.
    """
    service = LeadHandoverService(
        scorer=_default_scorer,
        get_active_agents_func=get_active_agents_and_employees,
        send_template_func=send_whatsapp_template,
        send_contact_func=send_whatsapp_contact,
        send_private_note_func=send_private_note,
        apply_label_func=apply_label,
        set_priority_func=set_priority,
        update_status_func=update_conversation_status,
        get_or_create_contact_func=get_or_create_contact,
        create_conversation_func=create_conversation,
        session_factory=SessionLocal,
        default_fallback_admins=DEFAULT_FALLBACK_ADMIN_NUMBERS,
    )
    return service.dispatch(
        conversation_id_or_data=conversation_id_or_data,
        customer_name=customer_name,
        customer_phone=customer_phone,
        intent=intent,
        location=location,
        property_type=property_type,
        budget=budget,
        conversation_summary=conversation_summary,
        cw_link=cw_link,
        inbox_id=inbox_id,
        raw_inquiry_text=raw_inquiry_text,
        db=db,
    )


from app.services.conversation_processor import ConversationQueueProcessor


@celery_app.task(bind=True, max_retries=3)
def process_conversation_queue(self, conversation_id: int, task_scheduled_time: float):
    """
    Processes all queued messages for a conversation if the user has stopped typing.
    Delegates to ConversationQueueProcessor domain service.
    """
    try:
        processor = ConversationQueueProcessor(
            celery_task=self,
            redis_client=redis_client,
            session_factory=SessionLocal,
            timeout_seconds=TIMEOUT_SECONDS,
        )
        return processor.process(conversation_id, task_scheduled_time)
    except Exception as exc:
        try:
            toggle_typing_status(conversation_id, "off")
        except Exception:
            pass
        logger.error(f"Error processing conversation {conversation_id}: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

@celery_app.task(bind=True, max_retries=3)
def process_wordpress_property(self, payload: dict):
    """
    Processes a raw WordPress webhook payload, extracts property details via LLM,
    and upserts into the database.
    """
    try:
        logger.info(f"Processing WordPress property: {payload.get('title')}")
        extracted_data = extract_wordpress_property(payload)
        
        title = payload.get("title", "")
        if not title:
            logger.error("No title found in WordPress payload, skipping.")
            return {"status": "failed", "reason": "no title"}
            
        # Optional fields from payload directly
        latitude = payload.get("latitude")
        longitude = payload.get("longitude")
        image_urls = payload.get("image_urls", [])
        if isinstance(image_urls, str):
            image_urls = [image_urls]
        db = SessionLocal()
        try:
            existing = db.query(Property).filter(Property.title == title).first()
            if existing:
                # Update existing property
                existing.search_corpus_markdown = payload.get("description", existing.search_corpus_markdown)
                existing.source_url = payload.get("source_url", existing.source_url)
                if latitude is not None: existing.latitude = latitude
                elif extracted_data.get("latitude") is not None: existing.latitude = extracted_data.get("latitude")
                
                if longitude is not None: existing.longitude = longitude
                elif extracted_data.get("longitude") is not None: existing.longitude = extracted_data.get("longitude")
                
                if image_urls: existing.image_urls = image_urls
                
                # Fields from extraction
                existing.property_type_sub = extracted_data.get("property_type_sub", existing.property_type_sub)
                existing.asking_price_myr = extracted_data.get("asking_price_myr", existing.asking_price_myr)
                existing.monthly_rental_income_myr = extracted_data.get("monthly_rental_income_myr", existing.monthly_rental_income_myr)
                existing.price_per_acre_myr = extracted_data.get("price_per_acre_myr", existing.price_per_acre_myr)
                existing.price_per_sqft_myr = extracted_data.get("price_per_sqft_myr", existing.price_per_sqft_myr)
                existing.implied_yield_pct = extracted_data.get("implied_yield_pct", existing.implied_yield_pct)
                existing.property_category = extracted_data.get("property_category", existing.property_category)
                existing.land_area_sqft = extracted_data.get("land_area_sqft", existing.land_area_sqft)
                existing.land_area_acres = extracted_data.get("land_area_acres", existing.land_area_acres)
                existing.land_area_sqm = extracted_data.get("land_area_sqm", existing.land_area_sqm)
                existing.built_up_area_sqft = extracted_data.get("built_up_area_sqft", existing.built_up_area_sqft)
                existing.tenure_type = extracted_data.get("tenure_type", existing.tenure_type)
                existing.zoning_type = extracted_data.get("zoning_type", existing.zoning_type)
                existing.title_status = extracted_data.get("title_status", existing.title_status)
                
                existing.crop_types = extracted_data.get("crop_types", existing.crop_types)
                existing.tree_count_estimate = extracted_data.get("tree_count_estimate", existing.tree_count_estimate)
                existing.tree_age_years = extracted_data.get("tree_age_years", existing.tree_age_years)
                existing.harvest_readiness = extracted_data.get("harvest_readiness", existing.harvest_readiness)
                
                existing.topography = extracted_data.get("topography", existing.topography)
                existing.water_source_types = extracted_data.get("water_source_types", existing.water_source_types)
                existing.has_natural_stream = extracted_data.get("has_natural_stream", existing.has_natural_stream)
                existing.has_pond = extracted_data.get("has_pond", existing.has_pond)
                existing.has_piping_system = extracted_data.get("has_piping_system", existing.has_piping_system)
                existing.is_flood_free = extracted_data.get("is_flood_free", existing.is_flood_free)
                
                existing.power_supply_amp = extracted_data.get("power_supply_amp", existing.power_supply_amp)
                existing.utilities_available = extracted_data.get("utilities_available", existing.utilities_available)
                existing.has_office = extracted_data.get("has_office", existing.has_office)
                existing.office_features = extracted_data.get("office_features", existing.office_features)
                existing.road_access_quality = extracted_data.get("road_access_quality", existing.road_access_quality)
                existing.is_fenced = extracted_data.get("is_fenced", existing.is_fenced)
                existing.has_worker_quarters = extracted_data.get("has_worker_quarters", existing.has_worker_quarters)
                
                existing.is_tenanted = extracted_data.get("is_tenanted", existing.is_tenanted)
                existing.lease_start_date = extracted_data.get("lease_start_date", existing.lease_start_date)
                existing.lease_end_date = extracted_data.get("lease_end_date", existing.lease_end_date)
                existing.current_tenant_use = extracted_data.get("current_tenant_use", existing.current_tenant_use)
                
                existing.street_address = extracted_data.get("street_address", existing.street_address)
                existing.area = extracted_data.get("area", existing.area)
                existing.city = extracted_data.get("city", existing.city)
                existing.state = extracted_data.get("state", existing.state)
                existing.nearby_landmarks = extracted_data.get("nearby_landmarks", existing.nearby_landmarks)
                
                existing.suitable_industries = extracted_data.get("suitable_industries", existing.suitable_industries)
                existing.key_highlights = extracted_data.get("key_highlights", existing.key_highlights)
                existing.risk_flags = extracted_data.get("risk_flags", existing.risk_flags)
                existing.listing_status = extracted_data.get("listing_status", existing.listing_status)
                
                if extracted_data.get("embedding_location") is not None:
                    existing.embedding_location = extracted_data["embedding_location"]
                if extracted_data.get("embedding_specs") is not None:
                    existing.embedding_specs = extracted_data["embedding_specs"]
                if extracted_data.get("embedding_features") is not None:
                    existing.embedding_features = extracted_data["embedding_features"]
                if extracted_data.get("embedding_suitability") is not None:
                    existing.embedding_suitability = extracted_data["embedding_suitability"]
                if extracted_data.get("embedding_overview") is not None:
                    existing.embedding_overview = extracted_data["embedding_overview"]
                
                db.commit()
                logger.info(f"Updated property: {existing.title} with full 12-category data and 5-aspect embeddings.")
                return {"status": "success", "action": "updated"}
            else:
                # Create new property
                new_prop = Property(
                    id=str(uuid.uuid4()),
                    source_url=payload.get("source_url", ""),
                    title=title,
                    listing_status=extracted_data.get("listing_status", "For Sale"),
                    property_category=extracted_data.get("property_category", []),
                    property_type_sub=extracted_data.get("property_type_sub"),
                    asking_price_myr=extracted_data.get("asking_price_myr", 0.0),
                    currency="MYR",
                    price_per_acre_myr=extracted_data.get("price_per_acre_myr"),
                    price_per_sqft_myr=extracted_data.get("price_per_sqft_myr"),
                    monthly_rental_income_myr=extracted_data.get("monthly_rental_income_myr"),
                    implied_yield_pct=extracted_data.get("implied_yield_pct"),
                    land_area_acres=extracted_data.get("land_area_acres"),
                    land_area_sqft=extracted_data.get("land_area_sqft"),
                    land_area_sqm=extracted_data.get("land_area_sqm"),
                    built_up_area_sqft=extracted_data.get("built_up_area_sqft"),
                    tenure_type=extracted_data.get("tenure_type"),
                    zoning_type=extracted_data.get("zoning_type"),
                    title_status=extracted_data.get("title_status"),
                    crop_types=extracted_data.get("crop_types", []),
                    tree_count_estimate=extracted_data.get("tree_count_estimate"),
                    tree_age_years=extracted_data.get("tree_age_years"),
                    harvest_readiness=extracted_data.get("harvest_readiness"),
                    topography=extracted_data.get("topography"),
                    water_source_types=extracted_data.get("water_source_types", []),
                    has_natural_stream=extracted_data.get("has_natural_stream", False),
                    has_pond=extracted_data.get("has_pond", False),
                    has_piping_system=extracted_data.get("has_piping_system", False),
                    is_flood_free=extracted_data.get("is_flood_free", True),
                    power_supply_amp=extracted_data.get("power_supply_amp"),
                    utilities_available=extracted_data.get("utilities_available", []),
                    has_office=extracted_data.get("has_office", False),
                    office_features=extracted_data.get("office_features"),
                    road_access_quality=extracted_data.get("road_access_quality"),
                    is_fenced=extracted_data.get("is_fenced", False),
                    has_worker_quarters=extracted_data.get("has_worker_quarters", False),
                    is_tenanted=extracted_data.get("is_tenanted", False),
                    lease_start_date=extracted_data.get("lease_start_date"),
                    lease_end_date=extracted_data.get("lease_end_date"),
                    current_tenant_use=extracted_data.get("current_tenant_use"),
                    street_address=extracted_data.get("street_address"),
                    area=extracted_data.get("area"),
                    city=extracted_data.get("city"),
                    state=extracted_data.get("state", "Pahang"),
                    country="Malaysia",
                    latitude=latitude or extracted_data.get("latitude"),
                    longitude=longitude or extracted_data.get("longitude"),
                    nearby_landmarks=extracted_data.get("nearby_landmarks", []),
                    suitable_industries=extracted_data.get("suitable_industries", []),
                    key_highlights=extracted_data.get("key_highlights", []),
                    risk_flags=extracted_data.get("risk_flags", []),
                    search_corpus_markdown=payload.get("description", f"{title}\n\n"),
                    agency_name="HOME IHC SDN. BHD.",
                    agent_name="Irene Leong",
                    agent_phone="+6011-65144931",
                    agent_whatsapp_url="https://my.mecard.my/1733211127",
                    image_urls=image_urls or extracted_data.get("image_urls", []),
                    embedding_location=extracted_data.get("embedding_location"),
                    embedding_specs=extracted_data.get("embedding_specs"),
                    embedding_features=extracted_data.get("embedding_features"),
                    embedding_suitability=extracted_data.get("embedding_suitability"),
                    embedding_overview=extracted_data.get("embedding_overview"),
                )
                db.add(new_prop)
                db.commit()
                return {"status": "success", "action": "created"}
        finally:
            db.close()
            
    except Exception as exc:
        logger.error(f"Error processing WordPress property: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(bind=True, max_retries=3)
def process_whatsapp_message(self, payload: dict):
    """
    Processes incoming WhatsApp messages.
    Extracts wamid, locks session, handles media, and forwards to LLM.
    """
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                
                contact_name = "Unknown"
                if contacts:
                    contact_name = contacts[0].get("profile", {}).get("name", "Unknown")

                for message in messages:
                    wamid = message.get("id")
                    phone_number = message.get("from")
                    message_type = message.get("type")
                    
                    if not wamid or not phone_number:
                        continue
                        
                    # Acquire distributed lock for this user's session
                    with SessionManager.lock_session(phone_number):
                        session = SessionManager.get_session(phone_number)
                        
                        if session.get("is_paused"):
                            logger.info(f"Session for {phone_number} is paused. Skipping AI processing.")
                            continue
                            
                        text = ""
                        media_url = ""
                        
                        # Handle different message types
                        if message_type == "text":
                            text = message.get("text", {}).get("body", "")
                        elif message_type in ["image", "audio", "document", "video"]:
                            media_id = message.get(message_type, {}).get("id")
                            if media_id:
                                # Fetch media from WhatsApp (Placeholder - need actual WA API call to fetch media binary)
                                # Assuming we have binary data in `media_binary`
                                # media_binary = fetch_whatsapp_media(media_id)
                                # media_url = upload_media(media_binary, f"{wamid}.{message_type}", "application/octet-stream")
                                logger.info(f"Received {message_type} with id {media_id}. MinIO upload pending WhatsApp API fetch.")
                                text = f"[{message_type} attached]"

                        # Log interaction
                        db = SessionLocal()
                        try:
                            # Save interaction log
                            log = InteractionLog(
                                wamid=wamid,
                                phone_number=phone_number,
                                direction="incoming",
                                message_text=text,
                                media_url=media_url
                            )
                            db.add(log)
                            db.commit()
                        except Exception as e:
                            logger.error(f"Failed to log interaction: {e}")
                            db.rollback()
                        finally:
                            db.close()
                            
                        # Update session state with message
                        session["collected_data"]["last_message"] = text
                        
                        SessionManager.save_session(phone_number, session)
                        
                        logger.info(f"Processed WhatsApp message {wamid} from {phone_number}. Text: {text}")
                        
        return {"status": "success"}
    except Exception as exc:
        logger.error(f"Error processing WhatsApp message: {exc}")
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@celery_app.task(bind=True, max_retries=2)
def run_lead_nurturing_daemon(self):
    """
    Accelerated lead nurturing daemon.
    Delegates to LeadNurturingManager OOP service layer.
    Periodically scans leads by temperature (Hot: 24h-72h, Warm: 3-7d, Cold: 7-14d).
    Strictly observes the Meta WhatsApp 24-hour customer care messaging window:
    - If customer interacted <= 24 hours ago: can send direct follow-up message via Chatwoot.
    - If customer interacted > 24 hours ago: free-form WhatsApp messages are prohibited;
      posts a private note in Chatwoot for human agent intervention or template dispatch.
    """
    try:
        from app.api.settings import get_system_toggle
        if not get_system_toggle("lead_nurturing_enabled", default=True):
            logger.info("[SKIPPED] Lead nurturing daemon: follow-up engine disabled via dashboard toggle.")
            return {"status": "skipped", "reason": "followup_disabled"}
    except Exception as te:
        logger.warning(f"Could not check follow-up toggle in daemon: {te}")

    from app.services.lead_nurturing import LeadNurturingManager
    logger.info("Starting lead nurturing daemon run via LeadNurturingManager...")
    try:
        manager = LeadNurturingManager(
            db_session=SessionLocal(),
            message_sender=send_message,
            note_sender=send_private_note
        )
        result = manager.run_cycle()
        logger.info(f"Completed lead nurturing daemon run: {result}")
        return result
    except Exception as exc:
        logger.error(f"Error in lead nurturing daemon: {exc}")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True, max_retries=2)
def generate_and_send_weekly_reports(self, output_dir: str = None, send_to_admins: bool = True):
    """
    Weekly Celery Beat task to compile and archive Buyer Database.xlsx and Owner Database.xlsx,
    and dispatch directly to Administrator WhatsApp lines.
    """
    logger.info("Executing weekly database reporting task...")
    try:
        from app.services.reporting import WeeklyDatabaseReportManager, DEFAULT_REPORTS_DIR
        target_dir = output_dir or DEFAULT_REPORTS_DIR
        manager = WeeklyDatabaseReportManager(output_dir=target_dir)
        outcome = manager.generate_and_dispatch(send_to_admins=send_to_admins)
        logger.info(f"Successfully generated and dispatched weekly reports: {outcome}")
        return {
            "status": "success",
            "reports": outcome.get("reports"),
            "dispatch_results": outcome.get("dispatch_results")
        }
    except Exception as exc:
        logger.error(f"Failed to generate/dispatch weekly reports: {exc}")
        raise self.retry(exc=exc, countdown=120)

