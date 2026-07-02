# Issue 001: Implement Phase 1 (Lead Inflow & Filtering)

## Objective
The goal is to review the existing n8n workflow (`kgNpbEYnHVtMnF28`) and begin aligning it strictly with **Phase 1: Lead Inflow & Filtering** as defined in `project/skills/context.md`.

## Instructions for Agent
1. **Read Context**: Review `project/skills/context.md` and `project/skills/credentials.md`.
2. **Access n8n**: Connect to the live n8n instance at `https://n8n.bentongland.com.my` using the JWT API key or the n8n-mcp tool.
3. **Analyze Workflow**: Extract the current JSON for workflow `kgNpbEYnHVtMnF28`. Compare the existing "Switch Role Routing" and "Lookup User Role" logic against the requirements in Phase 1.
4. **Implement Missing Routing**:
   - Ensure the AI Agent prompts clearly define the 7 roles: Buyer, Seller, Buyer + Seller, Non-Agent (Broker), Agent, Tenant, or Other.
   - Implement the "Two-Number Routing Logic" placeholders. (Sub-number 011-63044931 for filtering, Main number 011-65144951 for high-touch).
5. **Report**: Create an artifact or update `project/issues/001-implement-phase-1.md` with your status, what you changed in the n8n workflow, and any blockers. Once complete, delete this issue file.
