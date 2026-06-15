import json
import uuid

with open('n8n_chatwoot_workflow_user_current.json', 'r') as f:
    workflow = json.load(f)

nodes = workflow['nodes']
connections = workflow['connections']

# 1. Identify existing nodes
text_node = next(n for n in nodes if n['name'] == 'Text')
audio_node = next(n for n in nodes if n['name'] == 'Audio')
image_node = next(n for n in nodes if n['name'] == 'Image')
file_node = next(n for n in nodes if n['name'] == 'File')

# We need to remove connections from these 4 nodes to "AI Agent"
for node_name in ['Text', 'Audio', 'Image', 'File']:
    if node_name in connections and 'main' in connections[node_name]:
        connections[node_name]['main'] = [
            conn for conn in connections[node_name]['main']
            if conn[0]['node'] != 'AI Agent'
        ]

# 2. Add Postgres "Lookup User Role" node
lookup_node = {
    "parameters": {
        "operation": "executeQuery",
        "query": "SELECT role, name FROM users WHERE phone_number = $1;",
        "options": {
            "queryParameters": "={{ $node['Webhook'].json.body.sender.phone_number }}"
        }
    },
    "id": str(uuid.uuid4()),
    "name": "Lookup User Role",
    "type": "n8n-nodes-base.postgres",
    "position": [950, 300],
    "typeVersion": 2.4,
    "onError": "continueRegularOutput"
}
nodes.append(lookup_node)

# Connect Text/Audio/Image/File to Lookup User Role
for node_name in ['Text', 'Audio', 'Image', 'File']:
    if node_name not in connections:
        connections[node_name] = {"main": [[]]}
    if not connections[node_name]['main']:
        connections[node_name]['main'].append([])
    connections[node_name]['main'][0].append({
        "node": "Lookup User Role",
        "type": "main",
        "index": 0
    })

# 3. Add Switch Role Routing
switch_node = {
    "parameters": {
        "rules": {
            "values": [
                {
                    "conditions": {
                        "options": { "caseSensitive": False },
                        "conditions": [
                            {
                                "id": str(uuid.uuid4()),
                                "operator": { "type": "string", "operation": "equals" },
                                "leftValue": "={{ $json.role || 'customer' }}",
                                "rightValue": "admin"
                            }
                        ],
                        "combinator": "and"
                    },
                    "renameOutput": True,
                    "outputKey": "Admin"
                },
                {
                    "conditions": {
                        "options": { "caseSensitive": False },
                        "conditions": [
                            {
                                "id": str(uuid.uuid4()),
                                "operator": { "type": "string", "operation": "equals" },
                                "leftValue": "={{ $json.role || 'customer' }}",
                                "rightValue": "employee"
                            }
                        ],
                        "combinator": "and"
                    },
                    "renameOutput": True,
                    "outputKey": "Employee"
                }
            ]
        },
        "options": {
            "fallbackOutput": "extra"
        }
    },
    "id": str(uuid.uuid4()),
    "name": "Switch Role Routing",
    "type": "n8n-nodes-base.switch",
    "position": [1150, 300],
    "typeVersion": 3.2
}
nodes.append(switch_node)

connections["Lookup User Role"] = {
    "main": [
        [
            {
                "node": "Switch Role Routing",
                "type": "main",
                "index": 0
            }
        ]
    ]
}

# 4. Clone AI Agent to 3 distinct Agents
agent_original = next(n for n in nodes if n['name'] == 'AI Agent')
nodes.remove(agent_original)

customer_agent = dict(agent_original)
customer_agent['name'] = 'AI Agent - Customer'
customer_agent['id'] = str(uuid.uuid4())
customer_agent['position'] = [1350, 450]
customer_agent['parameters'] = dict(agent_original['parameters'])
customer_agent['parameters']['options'] = dict(agent_original['parameters']['options'])
customer_agent['parameters']['options']['systemMessage'] = (
    "You are an intelligent real estate assistant for Home IHC. "
    "You are talking to a CUSTOMER. You can assist them with inquiries, provide public information, and schedule viewings."
)

employee_agent = dict(agent_original)
employee_agent['name'] = 'AI Agent - Employee'
employee_agent['id'] = str(uuid.uuid4())
employee_agent['position'] = [1350, 300]
employee_agent['parameters'] = dict(agent_original['parameters'])
employee_agent['parameters']['options'] = dict(agent_original['parameters']['options'])
employee_agent['parameters']['options']['systemMessage'] = (
    "You are an internal real estate assistant for Home IHC. "
    "You are talking to an EMPLOYEE. You can assist them with customer data, lead tracking, and internal company info."
)

admin_agent = dict(agent_original)
admin_agent['name'] = 'AI Agent - Admin'
admin_agent['id'] = str(uuid.uuid4())
admin_agent['position'] = [1350, 150]
admin_agent['parameters'] = dict(agent_original['parameters'])
admin_agent['parameters']['options'] = dict(agent_original['parameters']['options'])
admin_agent['parameters']['options']['systemMessage'] = (
    "You are a master administrative AI for Home IHC. "
    "You are talking to an ADMIN. You have full access to all system data, employees, and customers."
)

nodes.extend([customer_agent, employee_agent, admin_agent])

# 5. Connect Switch to Agents
connections["Switch Role Routing"] = {
    "main": [
        [{"node": "AI Agent - Admin", "type": "main", "index": 0}],      # Admin
        [{"node": "AI Agent - Employee", "type": "main", "index": 0}],   # Employee
        [{"node": "AI Agent - Customer", "type": "main", "index": 0}]    # Fallback (Customer)
    ]
}

# 6. Reconnect Memory and Model to all 3 Agents
for ai_comp in ["Ollama Chat Model", "Simple Memory"]:
    if ai_comp in connections:
        conn_type = list(connections[ai_comp].keys())[0] # e.g. ai_languageModel or ai_memory
        connections[ai_comp][conn_type] = [
            [
                {"node": "AI Agent - Customer", "type": conn_type, "index": 0},
                {"node": "AI Agent - Employee", "type": conn_type, "index": 0},
                {"node": "AI Agent - Admin", "type": conn_type, "index": 0}
            ]
        ]

# 7. Connect all 3 Agents to Check Escalation
for agent_name in ["AI Agent - Customer", "AI Agent - Employee", "AI Agent - Admin"]:
    connections[agent_name] = {
        "main": [
            [
                {"node": "Check Escalation", "type": "main", "index": 0}
            ]
        ]
    }

# Ensure Check Escalation is moved further to the right to accommodate new nodes
check_esc_node = next(n for n in nodes if n['name'] == 'Check Escalation')
check_esc_node['position'][0] = 1600

# Fix remaining downstream node positions
for n in nodes:
    if n['position'][0] > 1100 and n['name'] not in ["Switch Role Routing", "AI Agent - Customer", "AI Agent - Employee", "AI Agent - Admin", "Check Escalation"]:
        n['position'][0] += 500

with open('n8n_chatwoot_workflow_rbac.json', 'w') as f:
    json.dump(workflow, f, indent=2)

print("Created RBAC workflow successfully.")
