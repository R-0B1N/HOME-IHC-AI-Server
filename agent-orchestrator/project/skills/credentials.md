# Project Credentials

The following credentials are required to interface with the production and development environments of the Real Estate WhatsApp AI CRM.

## Domains & Endpoints
- **Main Website**: bentongland.com.my
- **Server Dashboard**: dashboard.bentongland.com.my
- **n8n Instance**: https://n8n.bentongland.com.my

## n8n Integration
- **Workflow ID**: `kgNpbEYnHVtMnF28`
- **n8n API Key (JWT)**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzMmIzZjYzNC03OWYzLTRiMmUtYjBlZi0yYzFhMDFmMTNhYTIiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiNjAzZGZhMmQtYWJiNC00YmJlLTk5M2ItMzM3ZjRmMzAyNDJjIiwiaWF0IjoxNzgxNzkzNDQ3fQ.Esu6Iz90AEYe0KsyQd233Jcw_S0Gd5wv51Ox4eH_FOc`
- **Instructions**: Use the `n8n-mcp` if configured to edit workflows directly. Alternatively, use standard REST API requests (curl/python) utilizing the JWT key above to query, update, or analyze workflow `kgNpbEYnHVtMnF28`.

## Server SSH Access
- **Host**: homeihc-ai-server (or use the bentongland.com.my IP if DNS is routed)
- **Username**: `admin123`
- **Password**: `P@ssw0rd`
- **Deployment Path**: `~/opt/crm`
- **Instructions**: You may use the `run_command` tool to SSH into the server if you need to modify local docker-compose files, postgres configurations, or direct backend integrations. (e.g., `sshpass -p 'P@ssw0rd' ssh admin123@homeihc-ai-server`).
