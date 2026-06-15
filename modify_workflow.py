import json
import uuid

with open('n8n_chatwoot_workflow.json', 'r') as f:
    data = json.load(f)

# Find the AI Agent node
agent_idx = next(i for i, n in enumerate(data['nodes']) if n['name'] == 'AI Agent')
agent_node = data['nodes'][agent_idx]

auth_node = {
    "parameters": {
      "operation": "executeQuery",
      "query": "WITH new_user AS (\n  INSERT INTO users (phone_number, name)\n  VALUES ('{{ $node['Webhook'].json.body.sender.phone_number }}', '{{ $node['Webhook'].json.body.sender.name }}')\n  ON CONFLICT (phone_number) DO NOTHING\n  RETURNING role\n)\nSELECT role FROM new_user\nUNION ALL\nSELECT role FROM users WHERE phone_number = '{{ $node['Webhook'].json.body.sender.phone_number }}'\nLIMIT 1;"
    },
    "id": str(uuid.uuid4()),
    "name": "Lookup User Role",
    "type": "n8n-nodes-base.postgres",
    "typeVersion": 2.4,
    "position": [
      700,
      440
    ],
    "credentials": {
      "postgres": {
        "id": "postgres-local-id",
        "name": "Local Postgres"
      }
    }
}

if "Filter Inbound & Unassigned" in data['connections']:
    if "main" in data['connections']["Filter Inbound & Unassigned"]:
        data['connections']["Filter Inbound & Unassigned"]["main"] = [[
            {
              "node": "Lookup User Role",
              "type": "main",
              "index": 0
            }
        ]]

data['connections']["Lookup User Role"] = {
    "main": [
        [
            {
              "node": "Input type",
              "type": "main",
              "index": 0
            }
        ]
    ]
}

switch_role_node = {
    "parameters": {
      "rules": {
        "values": [
          {
            "conditions": {
              "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 2
              },
              "conditions": [
                {
                  "id": "1",
                  "leftValue": "={{ $node['Lookup User Role'].json.role }}",
                  "rightValue": "customer",
                  "operator": {
                    "type": "string",
                    "operation": "equals"
                  }
                }
              ],
              "combinator": "and"
            },
            "renameOutput": True,
            "outputKey": "Customer"
          },
          {
            "conditions": {
              "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 2
              },
              "conditions": [
                {
                  "id": "2",
                  "leftValue": "={{ $node['Lookup User Role'].json.role }}",
                  "rightValue": "employee",
                  "operator": {
                    "type": "string",
                    "operation": "equals"
                  }
                }
              ],
              "combinator": "and"
            },
            "renameOutput": True,
            "outputKey": "Employee"
          },
          {
            "conditions": {
              "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 2
              },
              "conditions": [
                {
                  "id": "3",
                  "leftValue": "={{ $node['Lookup User Role'].json.role }}",
                  "rightValue": "admin",
                  "operator": {
                    "type": "string",
                    "operation": "equals"
                  }
                }
              ],
              "combinator": "and"
            },
            "renameOutput": True,
            "outputKey": "Admin"
          }
        ]
      },
      "fallbackOutput": 0
    },
    "id": str(uuid.uuid4()),
    "name": "Switch Role",
    "type": "n8n-nodes-base.switch",
    "typeVersion": 3.2,
    "position": [
      1200,
      440
    ]
}

# Reroute the 4 processing nodes to "Switch Role" instead of "AI Agent"
for node_name in ["Input type", "Transcribe Audio", "Extract Image Analysis", "Extract Text from PDF"]:
    if node_name in data['connections']:
        for i, branch in enumerate(data['connections'][node_name]["main"]):
            for j, conn in enumerate(branch):
                if conn["node"] == "AI Agent":
                    data['connections'][node_name]["main"][i][j]["node"] = "Switch Role"

# Rename AI Agent to "Customer AI Agent"
agent_node["name"] = "Customer AI Agent"
agent_node["position"] = [1500, 200]
agent_node["parameters"]["options"]["systemMessage"] = "You are a customer service assistant. You are talking to a customer. Your goal is to identify their intent and guide them."

# Clone into Employee AI Agent
import copy
employee_agent = copy.deepcopy(agent_node)
employee_agent["id"] = str(uuid.uuid4())
employee_agent["name"] = "Employee AI Agent"
employee_agent["position"] = [1500, 440]
employee_agent["parameters"]["options"]["systemMessage"] = "You are an internal assistant for employees. You have access to broader company data. Respond professionally and helpfully to the employee."

# Clone into Admin AI Agent
admin_agent = copy.deepcopy(agent_node)
admin_agent["id"] = str(uuid.uuid4())
admin_agent["name"] = "Admin AI Agent"
admin_agent["position"] = [1500, 680]
admin_agent["parameters"]["options"]["systemMessage"] = "You are an administrative AI with full access. You are communicating with an Admin. You can execute high-level commands and query all database records."

data['nodes'].extend([auth_node, switch_role_node, employee_agent, admin_agent])

# Connect Switch Role to the 3 agents
data['connections']["Switch Role"] = {
    "main": [
        [{"node": "Customer AI Agent", "type": "main", "index": 0}], # Output 0: Customer
        [{"node": "Employee AI Agent", "type": "main", "index": 0}], # Output 1: Employee
        [{"node": "Admin AI Agent", "type": "main", "index": 0}]  # Output 2: Admin
    ]
}

# Connect all 3 agents to "Check Escalation"
for agent_name in ["Customer AI Agent", "Employee AI Agent", "Admin AI Agent"]:
    data['connections'][agent_name] = {
        "main": [
            [{"node": "Check Escalation", "type": "main", "index": 0}]
        ]
    }

# Also need to route Langchain inputs (Model and Memory) to the new agents
if "Ollama Chat Model" in data['connections']:
    data['connections']["Ollama Chat Model"]["ai_languageModel"] = [
        [
            {"node": "Customer AI Agent", "type": "ai_languageModel", "index": 0},
            {"node": "Employee AI Agent", "type": "ai_languageModel", "index": 0},
            {"node": "Admin AI Agent", "type": "ai_languageModel", "index": 0}
        ]
    ]

if "Simple Memory" in data['connections']:
    data['connections']["Simple Memory"]["ai_memory"] = [
        [
            {"node": "Customer AI Agent", "type": "ai_memory", "index": 0},
            {"node": "Employee AI Agent", "type": "ai_memory", "index": 0},
            {"node": "Admin AI Agent", "type": "ai_memory", "index": 0}
        ]
    ]

with open('n8n_chatwoot_workflow.json', 'w') as f:
    json.dump(data, f, indent=2)

print("Workflow successfully modified for RBAC!")
