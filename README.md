# Real Estate WhatsApp AI CRM Automation

This project provides an automated WhatsApp CRM solution tailored for the real estate industry. It integrates WhatsApp with n8n and Chatwoot, utilizing a fully on-premise AI deployment to handle customer inquiries efficiently while ensuring data privacy.

## Overview

The automation categorizes incoming WhatsApp messages from customers into specific intents (e.g., Owner looking to sell agricultural land, Buyer looking for a house, Tenant looking to rent) and responds with predefined, tailored templates.

It utilizes an on-premise AI model to guarantee absolute data sovereignty and avoid third-party cloud token costs. The system is highly efficient and designed to run on dedicated AI hardware.

## Architecture

This project is structured around **Option 2: Full On-Premise (Maximum Data Sovereignty)**:

- **n8n**: The core workflow automation tool that orchestrates message receiving, AI processing, and sending replies.
- **PostgreSQL**: A local database used to store customer interactions and maintain state, ensuring Personally Identifiable Information (PII) stays off third-party clouds.
- **Local AI Inference**: An AI model running locally (e.g., using Ollama or vLLM) on hardware such as the AMD Ryzen 7 7800X3D with an RTX 5070 Ti 16GB. This acts as the intelligence layer for classifying customer intents.
- **Chatwoot**: An open-source customer engagement suite integrated to allow human agents to take over and manage conversations seamlessly.

## Key Files

- `deploy_workflow.py`: A Python script that injects the updated real estate AI prompt (based on `Message Template.docx`) into the n8n workflow JSON and deploys it.
- `modify_workflow.py` / `add_rbac.py`: Scripts used to configure workflow settings and Role-Based Access Control (RBAC).
- `setup_database.sql`: SQL script to initialize the required database tables and permissions.
- `n8n_chatwoot_workflow.json`: The exported n8n workflow that connects the webhook, AI, and Chatwoot nodes.
- `Message Template.docx` / `.txt`: The source of truth for the predefined responses based on customer categories (Owner, Buyer, Tenant, etc.).

## Deployment

1. **Database Setup**: Run `setup_database.sql` against your local PostgreSQL instance to set up the necessary schemas.
2. **Workflow Configuration**: Use `deploy_workflow.py` to prepare the `n8n_chatwoot_workflow.json` with the latest prompts.
3. **n8n Import**: Import the configured JSON workflow into your local n8n instance.
4. **Webhook Tunneling**: Use Cloudflare Tunnels (`cloudflared`) to securely expose the n8n webhook to the Meta WhatsApp Cloud API without opening inbound firewall ports.

## Security & Privacy

Since this is a fully on-premise deployment:
- No PII redaction node is necessary as all data is processed by the local LLM.
- Zero data exposure to the open internet.
- Secure outbound tunnels (Cloudflare) are used instead of exposing ports directly.

## Hardware Requirements

Optimized for high-capacity AI PC builds:
- Recommended GPU: NVIDIA RTX 4070 Ti Super (16GB VRAM) or higher.
- Example Build: AMD Ryzen 7 7800X3D, RTX 5070 Ti 16GB, 32GB RAM.
