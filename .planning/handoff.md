# Project Handoff: Real Estate WhatsApp AI CRM Automation

## 1. Current Status
* **Architecture:** n8n orchestrating a WhatsApp AI assistant via Chatwoot webhooks, using PostgreSQL for state and data persistence.
* **State:** The AI is successfully receiving webhooks and processing them. RBAC logic has been successfully deployed to the active workflow (ID: `kgNpbEYnHVtMnF28`).
* **Active Blocker:** The PostgreSQL node in n8n is timing out because it is configured with a Cloudflare-proxied IP (`172.67.191.241`). Cloudflare proxy does not support port `5432`. This requires the user to update the database Host to the direct server IP, `localhost`, or a DNS-only subdomain.

## 2. What We Just Finished
* **Role-Based Access Control (RBAC):** Architected and deployed an RBAC routing switch in n8n. The flow now securely routes to separate AI Agents (`Customer`, `Employee`, `Admin`) based on the user's role defined in the Postgres `users` table.
* **Data-Loss Remediation:** Re-wired the workflow to execute the `Lookup User Role` Postgres node *prior* to message type assignment. This resolved a critical bug where the Postgres node overrode the incoming message payload (e.g., `[{"text": "hi"}]`), preserving the text for the AI Agent context.
* **Customer Categorization Prompts:** Engineered the `Customer AI Agent` system prompt using the user's `Message Template.docx`. The agent now autonomously categorizes leads (Owner, Buyer, Tenant, Broker) and structurally demands the required property details (Title, Layout, Durian Tree specs, etc.).
* **API Deployment:** Pushed the modified JSON workflow directly to the n8n production instance via the REST API.

## 3. Exact Next Step
1. **User Action:** Update the PostgreSQL credentials in n8n to bypass the Cloudflare proxy and establish a successful database connection.
2. **Phase 2 Implementation (Tool Calling & Data Retrieval):**
   * Architect the `leads_data` schema in PostgreSQL.
   * Construct LangChain Custom Tools within n8n.
   * Equip the `Customer AI Agent` with a Lead Extraction Tool to parse conversational data and execute `INSERT` statements into `leads_data`.
   * Equip `Employee` and `Admin` agents with Query Tools to retrieve and summarize lead information on demand.
