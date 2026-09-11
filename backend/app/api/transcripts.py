"""
FastAPI Router for Conversation PDF Transcripts.

Provides endpoints to download branded WhatsApp conversation PDF transcripts
and dispatch transcripts directly to customers via WhatsApp/Chatwoot.
"""

import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.services import chatwoot
from app.services.transcript import generate_conversation_transcript_pdf

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["Transcripts"]
)


class SendTranscriptResponse(BaseModel):
    status: str = Field(..., example="sent")
    conversation_id: int = Field(..., example=1042)
    filename: str = Field(..., example="Transcript_Conv_1042.pdf")
    detail: Optional[str] = None


@router.get(
    "/{conversation_id}/transcript.pdf",
    summary="Download conversation PDF transcript",
    description="Generates and returns an official, branded vector PDF transcript of the conversation.",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Conversation PDF file stream."
        },
        400: {"description": "Invalid conversation ID."},
        500: {"description": "Internal server error during PDF compilation."}
    }
)
def download_conversation_transcript(
    conversation_id: int,
    include_private_notes: bool = Query(
        False,
        description="Whether to include internal staff private notes in the transcript"
    )
):
    """
    Downloads the conversation transcript as a clean, vector PDF document.
    """
    if conversation_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation ID provided."
        )

    try:
        pdf_bytes, filename = generate_conversation_transcript_pdf(
            conversation_id=conversation_id,
            include_private_notes=include_private_notes
        )
    except Exception as e:
        logger.error(f"Error generating transcript PDF for conversation #{conversation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate conversation transcript: {str(e)}"
        )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/pdf"
        }
    )


@router.post(
    "/{conversation_id}/send-transcript-whatsapp",
    response_model=SendTranscriptResponse,
    summary="Send conversation transcript to customer via WhatsApp",
    description="Compiles the conversation transcript into a PDF, attaches it to the Chatwoot conversation to deliver to the customer, and logs a private audit note.",
    responses={
        200: {"description": "Transcript successfully dispatched via WhatsApp."},
        400: {"description": "Invalid conversation ID."},
        502: {"description": "Failed to dispatch PDF via Chatwoot / WhatsApp API."}
    }
)
def send_transcript_to_whatsapp(
    conversation_id: int,
    include_private_notes: bool = Query(
        False,
        description="Include internal notes (default False for customer-facing documents)"
    ),
    caption: Optional[str] = Query(
        None,
        description="Optional custom text message to accompany the PDF transcript document"
    )
):
    """
    Generates conversation transcript PDF, sends it to the customer via WhatsApp,
    and posts an internal confirmation private note in Chatwoot.
    """
    if conversation_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid conversation ID provided."
        )

    try:
        # 1. Generate PDF transcript
        pdf_bytes, filename = generate_conversation_transcript_pdf(
            conversation_id=conversation_id,
            include_private_notes=include_private_notes
        )
    except Exception as e:
        logger.error(f"Error generating transcript for conv #{conversation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate conversation transcript: {str(e)}"
        )

    # Default message accompanying the PDF
    message_text = caption or "📄 Here is the official transcript of your WhatsApp conversation with Home IHC."

    # 2. Send PDF as document attachment to Chatwoot conversation
    try:
        chatwoot.send_message_with_attachment(
            conversation_id=conversation_id,
            content=message_text,
            file_name=filename,
            file_content=pdf_bytes,
            content_type="application/pdf"
        )
    except Exception as e:
        logger.error(f"Failed to deliver transcript PDF attachment to Chatwoot conv #{conversation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to dispatch PDF transcript via Chatwoot: {str(e)}"
        )

    # 3. Post confirmation private note in Chatwoot
    audit_note = "📄 Conversation transcript (PDF) dispatched to customer via WhatsApp."
    try:
        chatwoot.send_private_note(conversation_id=conversation_id, content=audit_note)
    except Exception as e:
        logger.warning(f"Failed to post transcript confirmation note to conv #{conversation_id}: {e}")

    logger.info(f"Successfully dispatched transcript {filename} to conversation #{conversation_id}")
    return SendTranscriptResponse(
        status="sent",
        conversation_id=conversation_id,
        filename=filename,
        detail="Conversation transcript PDF successfully dispatched to customer via WhatsApp."
    )
