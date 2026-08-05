import yaml

with open('docker-compose.yml', 'r') as f:
    dc = yaml.safe_load(f)

with open('docker-compose.remote.yml', 'r') as f:
    dc_remote = yaml.safe_load(f)

# Merge dc_remote into dc
for k in ['services', 'volumes', 'networks']:
    if k in dc_remote:
        if k not in dc:
            dc[k] = {}
        for item, value in dc_remote[k].items():
            dc[k][item] = value

with open('docker-compose.merged.yml', 'w') as f:
    yaml.dump(dc, f, default_flow_style=False, sort_keys=False)
