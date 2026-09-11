"""
Chatwoot Conversation PDF Transcript Engine.

Generates clean, branded, multi-page vector PDF transcripts of WhatsApp conversations
using PyMuPDF (fitz) for Home IHC / BentongLand.
"""

import os
import io
import re
import math
import textwrap
import logging
import datetime
from typing import Tuple, List, Dict, Any, Optional

import fitz

from app.services import chatwoot

logger = logging.getLogger(__name__)

# --- Page Layout & Typography Constants ---
PAGE_WIDTH = 595.3   # A4 width in points
PAGE_HEIGHT = 841.9  # A4 height in points
MARGIN_X = 40.0
USABLE_WIDTH = PAGE_WIDTH - (2 * MARGIN_X)  # 515.3 pt

P1_MSG_START_Y = 206.0
P2_MSG_START_Y = 66.0
MAX_CONTENT_Y = 794.0
FOOTER_LINE_Y = 808.0
FOOTER_TEXT_Y = 822.0

BUBBLE_WIDTH = 420.0
BUBBLE_PADDING_X = 10.0
BUBBLE_PADDING_Y = 7.0
BUBBLE_GAP = 8.0

# Colors (RGB normalized 0.0 - 1.0)
COLOR_BRAND_EMERALD = (0.07, 0.28, 0.20)     # Home IHC Deep Emerald
COLOR_BRAND_GOLD = (0.78, 0.58, 0.16)        # BentongLand Accent Gold
COLOR_TEXT_MAIN = (0.12, 0.15, 0.18)         # Dark Charcoal Body
COLOR_TEXT_MUTED = (0.46, 0.50, 0.55)        # Muted Slate
COLOR_BORDER_SUBTLE = (0.84, 0.88, 0.92)     # Card Border
COLOR_BG_CARD = (0.975, 0.985, 0.995)        # Card Fill

# Bubble Themes
CUSTOMER_THEME = {
    "fill": (0.925, 0.968, 0.935),           # Mint Green
    "stroke": (0.78, 0.88, 0.80),
    "accent": (0.16, 0.52, 0.28),            # Forest Green Accent
    "sender_color": (0.12, 0.38, 0.22),
    "timestamp_color": (0.42, 0.48, 0.50),
    "text_color": (0.12, 0.15, 0.18),
    "align": "left",
}

ASSISTANT_THEME = {
    "fill": (0.935, 0.962, 0.995),          # Soft Sky / Azure
    "stroke": (0.78, 0.86, 0.94),
    "accent": (0.14, 0.38, 0.68),            # Corporate Navy Accent
    "sender_color": (0.12, 0.32, 0.60),
    "timestamp_color": (0.42, 0.48, 0.50),
    "text_color": (0.12, 0.15, 0.18),
    "align": "right",
}

PRIVATE_NOTE_THEME = {
    "fill": (1.0, 0.98, 0.91),               # Warm Amber
    "stroke": (0.92, 0.82, 0.55),
    "accent": (0.85, 0.58, 0.10),            # Gold Accent
    "sender_color": (0.65, 0.40, 0.05),
    "timestamp_color": (0.55, 0.50, 0.42),
    "text_color": (0.25, 0.20, 0.12),
    "align": "center",
}

ACTIVITY_THEME = {
    "fill": (0.955, 0.96, 0.97),             # Cool Neutral Grey
    "stroke": (0.86, 0.88, 0.90),
    "accent": (0.50, 0.55, 0.60),
    "sender_color": (0.40, 0.45, 0.50),
    "timestamp_color": (0.55, 0.58, 0.62),
    "text_color": (0.35, 0.38, 0.42),
    "align": "center",
}


def choose_font(text: str, is_bold: bool = False) -> str:
    """
    Selects standard Helvetica or CJK font depending on character set.
    PyMuPDF built-in 'china-s' natively supports Simplified Chinese and ASCII.
    """
    if any(ord(c) > 255 for c in text):
        return "china-s"
    return "helvetica-bold" if is_bold else "helv"


def format_timestamp(ts: Any) -> str:
    """
    Parses timestamps (unix seconds/millis or ISO string) and formats
    in Malaysia Standard Time (UTC+8).
    """
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e11:  # Milliseconds
                ts = ts / 1000.0
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        elif isinstance(ts, str):
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            return str(ts)

        myt = datetime.timezone(datetime.timedelta(hours=8))
        return dt.astimezone(myt).strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return str(ts)


def extract_sort_key(msg: Dict[str, Any]) -> float:
    """
    Normalizes created_at to a float unix timestamp for chronological sorting.
    """
    ts = msg.get("created_at")
    if isinstance(ts, (int, float)):
        return ts / 1000.0 if ts > 1e11 else float(ts)
    if isinstance(ts, str):
        try:
            dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            pass
    return float(msg.get("id") or 0)


def format_attachment_tags(attachments: List[Dict[str, Any]]) -> List[str]:
    """
    Formats Chatwoot message attachments into readable visual labels.
    """
    tags = []
    for att in attachments:
        f_type = (att.get("file_type") or "file").lower()
        data_url = att.get("data_url") or ""
        filename = ""
        if data_url:
            filename = data_url.split("?")[0].split("/")[-1]
            if len(filename) > 30:
                filename = filename[:27] + "..."

        if f_type == "image":
            tags.append(f"[Photo Attachment: {filename}]" if filename else "[Photo Attachment]")
        elif f_type == "audio":
            tags.append(f"[Voice Note / Audio: {filename}]" if filename else "[Voice Note / Audio]")
        elif f_type == "video":
            tags.append(f"[Video: {filename}]" if filename else "[Video Attachment]")
        elif f_type == "location":
            tags.append("[Shared Location Pin]")
        elif f_type == "contact":
            tags.append("[Shared Contact Card]")
        else:
            tags.append(f"[Document: {filename}]" if filename else f"[Attachment: {f_type}]")
    return tags


def measure_text_box(dummy_page: fitz.Page, text: str, width: float, fontname: str, fontsize: float) -> float:
    """
    Accurately measures the rendered vertical height of a multiline text block in PyMuPDF.
    """
    if not text.strip():
        return 0.0
    large_h = 4000.0
    rc = dummy_page.insert_textbox(
        fitz.Rect(0, 0, width, large_h),
        text,
        fontsize=fontsize,
        fontname=fontname
    )
    return max(13.0, large_h - rc)


def draw_first_page_header(
    page: fitz.Page,
    conversation_id: int,
    contact_name: str,
    phone_number: str,
    export_time_str: str,
    total_msgs: int,
    channel_name: str
):
    """
    Renders corporate branding, title, and metadata box on page 1.
    """
    # Top decorative accent banner
    page.draw_rect(fitz.Rect(MARGIN_X, 36, PAGE_WIDTH - MARGIN_X, 38.5), color=None, fill=COLOR_BRAND_EMERALD)

    # Corporate Branding
    page.insert_text(fitz.Point(MARGIN_X, 56), "HOME IHC SDN. BHD.", fontname="helvetica-bold", fontsize=13, color=COLOR_BRAND_EMERALD)
    
    brand_sub = "BentongLand.com.my  |  WhatsApp AI CRM"
    sub_w = fitz.get_text_length(brand_sub, fontname="helv", fontsize=9)
    page.insert_text(fitz.Point(PAGE_WIDTH - MARGIN_X - sub_w, 56), brand_sub, fontname="helv", fontsize=9, color=COLOR_TEXT_MUTED)

    page.draw_line(fitz.Point(MARGIN_X, 68), fitz.Point(PAGE_WIDTH - MARGIN_X, 68), color=COLOR_BORDER_SUBTLE, width=0.8)

    # Document Title & Subtitle
    page.insert_text(fitz.Point(MARGIN_X, 88), "Official WhatsApp Conversation Transcript", fontname="helvetica-bold", fontsize=15, color=(0.10, 0.14, 0.20))
    page.insert_text(fitz.Point(MARGIN_X, 102), "Certified Communication Archive • Confidential Customer Record", fontname="helv", fontsize=8.5, color=COLOR_TEXT_MUTED)

    # Metadata Box
    box_rect = fitz.Rect(MARGIN_X, 114, PAGE_WIDTH - MARGIN_X, 186)
    page.draw_rect(box_rect, color=COLOR_BORDER_SUBTLE, fill=COLOR_BG_CARD, width=0.8, radius=0.04)
    # Left brand strip inside card
    page.draw_rect(fitz.Rect(MARGIN_X, 114, MARGIN_X + 3.5, 186), color=None, fill=COLOR_BRAND_EMERALD)

    # Column 1
    page.insert_text(fitz.Point(54, 131), "CONVERSATION ID", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    page.insert_text(fitz.Point(54, 143), f"#{conversation_id}", fontname="helvetica-bold", fontsize=9.5, color=COLOR_TEXT_MAIN)

    page.insert_text(fitz.Point(54, 161), "PHONE NUMBER", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    page.insert_text(fitz.Point(54, 173), phone_number or "N/A", fontname="helv", fontsize=8.5, color=COLOR_TEXT_MAIN)

    # Column 2
    page.insert_text(fitz.Point(210, 131), "CUSTOMER NAME", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    cust_font = choose_font(contact_name, is_bold=True)
    page.insert_text(fitz.Point(210, 143), contact_name, fontname=cust_font, fontsize=9.5, color=COLOR_TEXT_MAIN)

    page.insert_text(fitz.Point(210, 161), "CHANNEL / INBOX", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    page.insert_text(fitz.Point(210, 173), channel_name, fontname="helv", fontsize=8.5, color=COLOR_TEXT_MAIN)

    # Column 3
    page.insert_text(fitz.Point(385, 131), "EXPORT TIMESTAMP", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    page.insert_text(fitz.Point(385, 143), export_time_str, fontname="helv", fontsize=8.5, color=COLOR_TEXT_MAIN)

    page.insert_text(fitz.Point(385, 161), "TOTAL MESSAGES", fontname="helvetica-bold", fontsize=7, color=COLOR_TEXT_MUTED)
    page.insert_text(fitz.Point(385, 173), f"{total_msgs} message{'s' if total_msgs != 1 else ''}", fontname="helvetica-bold", fontsize=9, color=COLOR_TEXT_MAIN)

    # Separator Line before message stream
    page.draw_line(fitz.Point(MARGIN_X, 196), fitz.Point(PAGE_WIDTH - MARGIN_X, 196), color=COLOR_BORDER_SUBTLE, width=0.5)


def draw_subsequent_page_header(page: fitz.Page, conversation_id: int, contact_name: str):
    """
    Renders compact running header on page 2 and beyond.
    """
    page.insert_text(fitz.Point(MARGIN_X, 48), "HOME IHC SDN. BHD.  |  WhatsApp Conversation Transcript", fontname="helvetica-bold", fontsize=8.5, color=COLOR_BRAND_EMERALD)
    
    right_str = f"Conv #{conversation_id}  •  {contact_name}"
    fn = choose_font(right_str)
    rw = fitz.get_text_length(right_str, fontname=fn, fontsize=8)
    page.insert_text(fitz.Point(PAGE_WIDTH - MARGIN_X - rw, 48), right_str, fontname=fn, fontsize=8, color=COLOR_TEXT_MUTED)
    
    page.draw_line(fitz.Point(MARGIN_X, 54), fitz.Point(PAGE_WIDTH - MARGIN_X, 54), color=COLOR_BORDER_SUBTLE, width=0.5)


def draw_footers_all_pages(doc: fitz.Document):
    """
    Applies running page numbers ('Page X of Y') and confidentiality disclaimer
    across every generated page in the document.
    """
    total_pages = len(doc)
    for i, page in enumerate(doc, 1):
        page.draw_line(fitz.Point(MARGIN_X, FOOTER_LINE_Y), fitz.Point(PAGE_WIDTH - MARGIN_X, FOOTER_LINE_Y), color=COLOR_BORDER_SUBTLE, width=0.5)
        
        footer_text = f"Page {i} of {total_pages}   |   Generated by Home IHC WhatsApp AI CRM   |   Confidential"
        tw = fitz.get_text_length(footer_text, fontname="helv", fontsize=7.5)
        start_x = (PAGE_WIDTH - tw) / 2.0
        page.insert_text(fitz.Point(start_x, FOOTER_TEXT_Y), footer_text, fontname="helv", fontsize=7.5, color=COLOR_TEXT_MUTED)


def split_text_to_fit_page(
    dummy_page: fitz.Page,
    text: str,
    width: float,
    max_height: float,
    fontname: str,
    fontsize: float
) -> List[str]:
    """
    Safely splits oversized messages across multiple pages so content never overflows
    or clips outside printable page boundaries.
    """
    lines = []
    # Pre-wrap any very long unbroken lines
    for raw_line in text.split("\n"):
        if len(raw_line) > 100:
            lines.extend(textwrap.wrap(raw_line, width=90))
        else:
            lines.append(raw_line)

    chunks = []
    current_lines = []

    for line in lines:
        test_str = "\n".join(current_lines + [line])
        h = measure_text_box(dummy_page, test_str, width, fontname, fontsize)
        if h > max_height and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks or [text]


def draw_bubble_on_page(
    page: fitz.Page,
    theme: Dict[str, Any],
    sender_name: str,
    timestamp: str,
    content: str,
    x0: float,
    y0: float,
    width: float,
    height: float,
    body_font: str,
    is_split_continuation: bool = False
):
    """
    Renders a styled WhatsApp vector bubble with accent bar, sender info, and body text.
    """
    x1 = x0 + width
    y1 = y0 + height

    # Background card
    page.draw_rect(
        fitz.Rect(x0, y0, x1, y1),
        color=theme["stroke"],
        fill=theme["fill"],
        width=0.75,
        radius=0.03
    )

    # Accent vertical stripe
    accent_w = 3.5
    if theme["align"] == "right":
        page.draw_rect(fitz.Rect(x1 - accent_w, y0, x1, y1), color=None, fill=theme["accent"])
    else:
        page.draw_rect(fitz.Rect(x0, y0, x0 + accent_w, y1), color=None, fill=theme["accent"])

    # Sender & Timestamp line
    sender_fn = choose_font(sender_name, is_bold=True)
    sender_x = x0 + BUBBLE_PADDING_X + (2.0 if theme["align"] != "right" else 0.0)
    page.insert_text(
        fitz.Point(sender_x, y0 + 14.0),
        sender_name,
        fontname=sender_fn,
        fontsize=8.2,
        color=theme["sender_color"]
    )

    sw = fitz.get_text_length(sender_name, fontname=sender_fn, fontsize=8.2)
    time_label = f"•  {timestamp}" if not is_split_continuation else f"•  {timestamp} (Cont.)"
    page.insert_text(
        fitz.Point(sender_x + sw + 5.0, y0 + 14.0),
        time_label,
        fontname="helv",
        fontsize=7.2,
        color=theme["timestamp_color"]
    )

    # Message text body
    text_rect = fitz.Rect(
        x0 + BUBBLE_PADDING_X + (2.0 if theme["align"] != "right" else 0.0),
        y0 + 21.0,
        x1 - BUBBLE_PADDING_X - (2.0 if theme["align"] == "right" else 0.0),
        y1 - 5.0
    )
    page.insert_textbox(
        text_rect,
        content,
        fontsize=8.8,
        fontname=body_font,
        color=theme["text_color"]
    )


def generate_conversation_transcript_pdf(
    conversation_id: int,
    include_private_notes: bool = False
) -> Tuple[bytes, str]:
    """
    Generates a clean, branded, multi-page vector PDF transcript for a given Chatwoot conversation.

    Args:
        conversation_id: The Chatwoot conversation ID.
        include_private_notes: Whether to include internal staff notes in the transcript.

    Returns:
        tuple[bytes, str]: (pdf_bytes, filename)
    """
    logger.info(f"Generating PDF transcript for conversation #{conversation_id} (include_private_notes={include_private_notes})")

    # 1. Fetch conversation messages from Chatwoot
    messages = chatwoot.get_conversation_messages(conversation_id)
    if not isinstance(messages, list):
        messages = []

    # 2. Fetch conversation details / metadata
    conv_details = chatwoot.get_conversation_details(conversation_id) or {}
    meta = conv_details.get("meta", {})
    sender_meta = meta.get("sender", {})

    contact_name = sender_meta.get("name") or sender_meta.get("available_name")
    phone_number = sender_meta.get("phone_number") or sender_meta.get("identifier")
    email = sender_meta.get("email")
    inbox_id = conv_details.get("inbox_id")

    # Fallback extraction from incoming messages payload if conversation meta was incomplete
    if not contact_name or not phone_number:
        for msg in messages:
            m_type = msg.get("message_type")
            if m_type in [0, "0", "incoming"]:
                s = msg.get("sender") or {}
                if not contact_name:
                    contact_name = s.get("name") or s.get("available_name")
                if not phone_number:
                    phone_number = s.get("phone_number") or s.get("identifier")
                if not email:
                    email = s.get("email")
                if contact_name and phone_number:
                    break

    # Fallback lookup from database Customer table if available
    if not contact_name or not phone_number:
        try:
            from app.db.models import SessionLocal, Customer
            db = SessionLocal()
            try:
                cust = None
                if phone_number:
                    cust = db.query(Customer).filter(Customer.id == phone_number).first()
                if not cust:
                    # Scan customers whose conversation_ids include this conversation
                    all_custs = db.query(Customer).all()
                    for c in all_custs:
                        c_ids = c.conversation_ids or []
                        if conversation_id in c_ids or str(conversation_id) in [str(x) for x in c_ids]:
                            cust = c
                            break
                if cust:
                    contact_name = contact_name or cust.contact_name
                    phone_number = phone_number or cust.id
                    email = email or cust.email
            finally:
                db.close()
        except Exception as db_err:
            logger.debug(f"DB fallback notice for transcript #{conversation_id}: {db_err}")

    # Set default values for missing contact fields
    contact_name = contact_name or "Valued Client"
    phone_number = phone_number or "N/A"
    channel_name = f"WhatsApp • Inbox {inbox_id}" if inbox_id else "WhatsApp • Bentong Land"

    # 3. Sort messages chronologically (oldest first)
    messages.sort(key=extract_sort_key)

    # 4. Filter messages (skip private notes unless include_private_notes=True)
    filtered_messages = []
    for msg in messages:
        is_private = bool(msg.get("private"))
        if is_private and not include_private_notes:
            continue
        filtered_messages.append(msg)

    # Current export timestamp in Malaysia Time
    myt = datetime.timezone(datetime.timedelta(hours=8))
    export_time_str = datetime.datetime.now(myt).strftime("%d %b %Y, %I:%M %p")

    # 5. Build PDF Document using PyMuPDF
    doc = fitz.open()
    dummy_doc = fitz.open()
    dummy_page = dummy_doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

    # Create first page and draw top branding & metadata
    current_page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    draw_first_page_header(
        page=current_page,
        conversation_id=conversation_id,
        contact_name=contact_name,
        phone_number=phone_number,
        export_time_str=export_time_str,
        total_msgs=len(filtered_messages),
        channel_name=channel_name
    )

    current_y = P1_MSG_START_Y

    # Handle empty conversation case
    if not filtered_messages:
        empty_rect = fitz.Rect(MARGIN_X, 220.0, PAGE_WIDTH - MARGIN_X, 280.0)
        current_page.draw_rect(empty_rect, color=COLOR_BORDER_SUBTLE, fill=COLOR_BG_CARD, width=0.8, radius=0.04)
        empty_msg = "No conversation messages recorded."
        ew = fitz.get_text_length(empty_msg, fontname="helv", fontsize=9.5)
        current_page.insert_text(fitz.Point((PAGE_WIDTH - ew) / 2.0, 255.0), empty_msg, fontname="helv", fontsize=9.5, color=COLOR_TEXT_MUTED)
    else:
        # Stream messages sequentially
        for msg in filtered_messages:
            is_private = bool(msg.get("private"))
            m_type = msg.get("message_type")

            # Determine theme & alignment
            if is_private:
                theme = PRIVATE_NOTE_THEME
                width = 460.0
                x0 = (PAGE_WIDTH - width) / 2.0
            elif m_type in [1, "1", "outgoing", 3, "3", "template"]:
                theme = ASSISTANT_THEME
                width = BUBBLE_WIDTH
                x0 = PAGE_WIDTH - MARGIN_X - width
            elif m_type in [2, "2", "activity"]:
                theme = ACTIVITY_THEME
                width = 440.0
                x0 = (PAGE_WIDTH - width) / 2.0
            else:
                # Customer message
                theme = CUSTOMER_THEME
                width = BUBBLE_WIDTH
                x0 = MARGIN_X

            # Determine sender title
            sender_obj = msg.get("sender") or {}
            sender_name_raw = sender_obj.get("name")

            if is_private:
                sender_display = f"Private Staff Note ({sender_name_raw or 'Agent'})"
            elif m_type in [1, "1", "outgoing", 3, "3", "template"]:
                if sender_name_raw and sender_name_raw.lower() not in ["bot", "system", "app", ""]:
                    sender_display = sender_name_raw if "Home IHC" in sender_name_raw else f"{sender_name_raw} (Home IHC)"
                else:
                    sender_display = "Irene Leong (Home IHC)"
            elif m_type in [2, "2", "activity"]:
                sender_display = "System Update"
            else:
                sender_display = sender_name_raw or contact_name or "Customer"

            # Timestamp string
            msg_ts_str = format_timestamp(msg.get("created_at"))

            # Content & Attachments
            content = (msg.get("content") or "").strip()
            attachments = msg.get("attachments") or []
            att_tags = format_attachment_tags(attachments)

            if att_tags:
                tag_block = "\n".join(att_tags)
                content = f"{content}\n\n{tag_block}" if content else tag_block

            if not content:
                content = "[Empty message]"

            # Font selection
            body_font = choose_font(content)
            interior_text_w = width - (2 * BUBBLE_PADDING_X) - 4.0

            # Max height allowed on a fresh page
            max_page_available_h = MAX_CONTENT_Y - P2_MSG_START_Y - 40.0

            # Measure full content height
            total_text_h = measure_text_box(dummy_page, content, interior_text_w, body_font, 8.8)
            total_bubble_h = 28.0 + total_text_h

            # If oversized message, split across multiple page chunks
            if total_bubble_h > max_page_available_h:
                content_chunks = split_text_to_fit_page(
                    dummy_page,
                    content,
                    interior_text_w,
                    max_page_available_h - 40.0,
                    body_font,
                    8.8
                )
            else:
                content_chunks = [content]

            for chunk_idx, chunk_text in enumerate(content_chunks):
                chunk_text_h = measure_text_box(dummy_page, chunk_text, interior_text_w, body_font, 8.8)
                chunk_bubble_h = 28.0 + chunk_text_h

                # Check if bubble fits on current page
                if current_y + chunk_bubble_h > MAX_CONTENT_Y:
                    current_page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
                    draw_subsequent_page_header(current_page, conversation_id, contact_name)
                    current_y = P2_MSG_START_Y

                # Render bubble
                draw_bubble_on_page(
                    page=current_page,
                    theme=theme,
                    sender_name=sender_display if chunk_idx == 0 else f"{sender_display} (Part {chunk_idx + 1}/{len(content_chunks)})",
                    timestamp=msg_ts_str,
                    content=chunk_text,
                    x0=x0,
                    y0=current_y,
                    width=width,
                    height=chunk_bubble_h,
                    body_font=body_font,
                    is_split_continuation=(chunk_idx > 0)
                )

                current_y += chunk_bubble_h + BUBBLE_GAP

    # 6. Pass 2: Apply dynamic footers with total page count across all pages
    draw_footers_all_pages(doc)

    pdf_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    dummy_doc.close()

    filename = f"Transcript_Conv_{conversation_id}.pdf"
    logger.info(f"Generated PDF transcript {filename} ({len(pdf_bytes)} bytes)")
    return pdf_bytes, filename


class ConversationTranscriptEngine:
    """
    Object-Oriented Conversation Transcript Generator.
    Encapsulates message aggregation, multi-page vector layout,
    CJK typography, and automated WhatsApp/Chatwoot dispatch.
    """

    def __init__(self, conversation_id: int, include_private_notes: bool = False):
        self.conversation_id = conversation_id
        self.include_private_notes = include_private_notes

    def generate(self) -> Tuple[bytes, str]:
        """Generates the official PDF transcript."""
        return generate_conversation_transcript_pdf(
            conversation_id=self.conversation_id,
            include_private_notes=self.include_private_notes
        )

    def dispatch_whatsapp(self, custom_message: Optional[str] = None) -> Dict[str, Any]:
        """Generates PDF and dispatches to WhatsApp conversation in Chatwoot."""
        pdf_bytes, filename = self.generate()
        msg = custom_message or "Here is the official PDF transcript of our conversation for your records. 😊"
        chatwoot.send_message_with_attachment(
            conversation_id=self.conversation_id,
            content=msg,
            file_name=filename,
            file_content=pdf_bytes,
            content_type="application/pdf"
        )
        chatwoot.send_private_note(
            self.conversation_id,
            f"📄 **Conversation Transcript {filename} ({len(pdf_bytes):,} bytes) dispatched to customer via WhatsApp.**"
        )
        return {
            "status": "sent",
            "conversation_id": self.conversation_id,
            "filename": filename,
            "bytes": len(pdf_bytes)
        }

