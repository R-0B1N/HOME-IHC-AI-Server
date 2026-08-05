#!/bin/bash
echo P@ssw0rd | sudo -S cp /home/admin123/config.yml /opt/crm/tunnel/config.yml
echo P@ssw0rd | sudo -S cp /home/admin123/docker-compose.yml /opt/crm/docker-compose.yml
echo P@ssw0rd | sudo -S cp -r /home/admin123/backend/* /opt/crm/backend/
echo P@ssw0rd | sudo -S rm -rf /opt/crm/property-dashboard
echo P@ssw0rd | sudo -S cp -r /home/admin123/property-dashboard /opt/crm/property-dashboard
echo P@ssw0rd | sudo -S chown -R admin123:admin123 /opt/crm/backend /opt/crm/property-dashboard
cd /opt/crm && echo P@ssw0rd | sudo -S docker compose up -d --build property-dashboard api worker cloudflared
