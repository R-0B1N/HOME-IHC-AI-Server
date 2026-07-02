# Real Estate WhatsApp AI CRM Automation

## 1. Executive Summary & Project Vision
This project establishes a fully automated, AI-assisted lead management ecosystem using n8n orchestration, LLMs, and pCloud storage. It captures leads across fragmented platforms, automates multi-tiered nurturing based on real-time client intent, and manages secure document distribution from initial touchpoint to final closing.

## 2. Phased Workflow Architecture

### Phase 1: Lead Inflow & Filtering
- **Multi-Channel Aggregation**: Consolidates leads from Email, WhatsApp, Property websites, Bentongland website, Instagram, Facebook, YouTube, Xiaohongshu, and WeChat.
- **Two-Number Routing Logic**:
  - **AI Customer Service Sub-number (011-63044931)**: Handles greetings, preliminary FAQs, and instant property info distribution via pCloud.
  - **Main Number (011-65144951)**: High-touch conversion and volume management (leads are bridged here once qualified).
- **Initial Classification**: AI categorizes leads into: Buyer, Seller, Buyer + Seller, Non-Agent (Broker), Agent (segmented by area), Tenant, or Other.

### Phase 2: Before Viewing (AI Pre-Nurturing)
- **Trigger & Sync**: Initiated by sales personnel via a system button; auto-syncs appointments to Google Calendar.
- **Intent Tagging (WhatsApp Labels)**:
  - **Hot**: High intent, follow-up every 1-7 days.
  - **Warm**: Interested but observing, follow-up every 7-14 days.
  - **Cooling**: Low intent, follow-up every 2 weeks with greeting messages or property recommendations.

### Phase 3: After Viewing (Automated Follow-Up)
- **Document Dispatch**: n8n workflow triggers and sends the Customer Property Acknowledgement Letter.
- **Accelerated Follow-Up Matrix**:
  - **Hot**: Completed within 24 - 72 hours.
  - **Warm**: Completed within 3 - 7 days.
  - **Cooling**: Periodic maintenance after 7 days.

### Phase 4: Closed Sales (Retention)
- **Tagging**: Lead tagged as "Closed Sales".
- **Migration**: Data migrated to primary CRM database for lifecycle management (satisfaction, loyalty, referrals, upselling).

## 3. Data Architecture & Privacy Schema
- **Locally Hosted PostgreSQL Database**: Stores all client chat histories, intent classifications, and contact details securely alongside the n8n orchestration engine. Zero exposure to the open internet.
- **Hybrid Asset Management (pCloud)**: Secure file repository. Local database stores encrypted URL links pointing to viewing PDFs and property images.

## 4. Current Workflow Progress (n8n)
- **Workflow ID**: `kgNpbEYnHVtMnF28`
- **Current State**: Implements webhook parsing, multimedia download (audio, images, PDFs), role lookup, and routes to three basic LangChain Agents (Customer, Employee, Admin). Escallation logic is also partially defined.
