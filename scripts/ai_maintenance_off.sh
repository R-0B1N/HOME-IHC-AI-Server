#!/bin/bash
# Disable Maintenance Mode for AI
# This script brings back up the Celery worker containers.
# The AI will start processing the backlog of queued messages.

echo "🟢 Bringing up AI Worker for PRODUCTION..."
docker compose -f /home/admin123/whatsapp-ai-prod/docker-compose.production.yml start worker_production
echo "✅ Production AI Worker started."

echo "🟢 Bringing up AI Worker for STAGING..."
docker compose -f /home/admin123/whatsapp-ai-staging/docker-compose.staging.yml start worker_staging
echo "✅ Staging AI Worker started."

echo "🎉 AI Maintenance Mode is now OFF. Processing resumed."
