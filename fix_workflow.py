import json
import urllib.request

api_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIzMmIzZjYzNC03OWYzLTRiMmUtYjBlZi0yYzFhMDFmMTNhYTIiLCJpc3MiOiJuOG4iLCJhdWQiOiJwdWJsaWMtYXBpIiwianRpIjoiZDU5ZmFkNTEtZjU1NC00ZGU3LWExZWQtMTlkMmRlZjFiMTMwIiwiaWF0IjoxNzgxMjU2MTM0fQ.FKutC4qVvjv1GgTgIN9q4qlCoJ56M4OLh77u2ZR7pGo"
workflow_id = "kgNpbEYnHVtMnF28"
url = f"https://n8n.bentongland.com.my/api/v1/workflows/{workflow_id}"

# 1. Download current workflow
req = urllib.request.Request(url, method='GET')
req.add_header('X-N8N-API-KEY', api_key)
req.add_header('User-Agent', 'Mozilla/5.0')
with urllib.request.urlopen(req) as response:
    workflow = json.loads(response.read().decode('utf-8'))

conns = workflow['connections']

# 2. Re-wire Filter Inbound & Unassigned -> Lookup User Role -> Input type2
if "Filter Inbound & Unassigned" in conns:
    conns["Filter Inbound & Unassigned"]["main"] = [[
        {"node": "Lookup User Role", "type": "main", "index": 0}
    ]]
conns["Lookup User Role"] = {
    "main": [[
        {"node": "Input type2", "type": "main", "index": 0}
    ]]
}

# 3. Re-wire Text, Audio, Image, File directly to Switch Role Routing
for node_name in ["Text", "Audio", "Image", "File"]:
    if node_name in conns:
        conns[node_name]["main"] = [[
            {"node": "Switch Role Routing", "type": "main", "index": 0}
        ]]

# 4. Rearrange positions so it looks nice
for node in workflow['nodes']:
    if node['name'] == 'Lookup User Role':
        node['position'] = [200, 460]
    elif node['name'] == 'Input type2':
        node['position'] = [400, 460]

# 5. Upload back
payload = {
    "name": workflow['name'],
    "nodes": workflow['nodes'],
    "connections": workflow['connections'],
    "settings": {}
}

data = json.dumps(payload).encode('utf-8')
req_put = urllib.request.Request(url, data=data, method='PUT')
req_put.add_header('X-N8N-API-KEY', api_key)
req_put.add_header('Content-Type', 'application/json')
req_put.add_header('User-Agent', 'Mozilla/5.0')

try:
    with urllib.request.urlopen(req_put) as response:
        print(f"PUT Status Code: {response.getcode()}")
except urllib.error.HTTPError as e:
    print(f"PUT Status Code: {e.code}")
    print(f"PUT Error: {e.read().decode('utf-8')}")
