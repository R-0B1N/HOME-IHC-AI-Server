#!/bin/bash
# Enable Maintenance Mode for AI
# This script brings down the Celery worker containers.
# Messages will queue up in Redis but the AI will not respond.

echo "🚨 Bringing down AI Worker for PRODUCTION..."
docker compose -f /home/admin123/whatsapp-ai-prod/docker-compose.production.yml stop worker_production
echo "✅ Production AI Worker stopped."

echo "🚨 Bringing down AI Worker for STAGING..."
docker compose -f /home/admin123/whatsapp-ai-staging/docker-compose.staging.yml stop worker_staging
echo "✅ Staging AI Worker stopped."

echo "⚠️ AI Maintenance Mode is now ON. Messages are queuing."
