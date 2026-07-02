# Real Estate CRM Validation Contract

The Validator agent must use this contract to verify any work done by the Worker agent. Do not accept any workflow changes unless they meet these criteria.

## 1. Error Handling
- Every n8n workflow must have an Error Trigger node or a defined error handling path.
- Workflows must not silently fail; they must log failures or alert an admin.

## 2. Lead Classification
- If the workflow handles inflow (Phase 1), it must accurately parse the payload and classify the user into one of: Buyer, Seller, Buyer+Seller, Broker, Agent, Tenant.
- The routing must include a fallback/default route for unclassified leads.

## 3. Webhook Security
- All incoming webhooks (e.g. from WhatsApp) must be authenticated (e.g. basic auth or header check). No open webhooks are permitted in production.

## 4. State Management
- Data must be passed correctly between nodes. Check the expressions (e.g. `{{ $json.body }}`) to ensure they reference existing output from previous nodes.
