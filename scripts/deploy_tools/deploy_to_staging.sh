#!/bin/bash
echo "Uploading docker-compose and config..."
scp -o StrictHostKeyChecking=no ./docker-compose.remote.yml admin123@homeihc-ai-server:/tmp/docker-compose.yml
scp -o StrictHostKeyChecking=no ./config.remote.yml admin123@homeihc-ai-server:/tmp/config.yml

echo "Uploading backend..."
rsync -avz --exclude 'venv' --exclude '__pycache__' --exclude '.env' -e "ssh -o StrictHostKeyChecking=no" ./backend/ admin123@homeihc-ai-server:/tmp/backend/

echo "Uploading property-dashboard..."
rsync -avz --exclude 'node_modules' --exclude 'dist' -e "ssh -o StrictHostKeyChecking=no" ./property-dashboard/ admin123@homeihc-ai-server:/tmp/property-dashboard/

echo "Running sudo commands to deploy..."
ssh -o StrictHostKeyChecking=no admin123@homeihc-ai-server '
  echo P@ssw0rd | sudo -S cp /tmp/docker-compose.yml /opt/crm/docker-compose.yml
  echo P@ssw0rd | sudo -S cp /tmp/config.yml /opt/crm/tunnel/config.yml
  echo P@ssw0rd | sudo -S cp -r /tmp/backend/* /opt/crm/backend/
  echo P@ssw0rd | sudo -S rm -rf /opt/crm/property-dashboard/*
  echo P@ssw0rd | sudo -S cp -r /tmp/property-dashboard/* /opt/crm/property-dashboard/
  echo P@ssw0rd | sudo -S chown -R admin123:admin123 /opt/crm/backend /opt/crm/property-dashboard
  cd /opt/crm
  echo P@ssw0rd | sudo -S docker compose up -d --build property-dashboard api worker cloudflared
'
