const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28.json', 'utf8'));

// 1. Filter Node
let filterNode = data.nodes.find(n => n.name === 'Filter Inbound & Unassigned');
if (filterNode) {
    let eventCond = filterNode.parameters.conditions.conditions.find(c => c.leftValue === '={{ $json.body.event }}');
    if (eventCond) {
        eventCond.operator = {
            "type": "string",
            "operation": "regex"
        };
        eventCond.rightValue = '^message_(created|updated)$';
    }
}

// 2. Transcribe Audio node
let audioNode = data.nodes.find(n => n.name === 'Transcribe Audio');
if (audioNode) {
    audioNode.parameters = {
        "method": "POST",
        "url": "http://crm-whisper:8000/v1/audio/transcriptions",
        "sendBody": true,
        "contentType": "multipart-form-data",
        "bodyParameters": {
            "parameters": [
                {
                    "name": "model",
                    "value": "base"
                },
                {
                    "name": "response_format",
                    "value": "json"
                },
                {
                    "parameterType": "form-data-multipart",
                    "name": "file",
                    "inputDataFieldName": "data"
                }
            ]
        },
        "sendInputData": false,
        "options": {}
    };
    
    // In n8n v4, if sendInputData is false, it uses the bodyParameters.
}

// 3. Audio node
let audioSetNode = data.nodes.find(n => n.name === 'Audio');
if (audioSetNode) {
    audioSetNode.parameters.assignments.assignments[0].value = '={{ $json.text }}';
}

fs.writeFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', JSON.stringify(data, null, 2));
console.log("Fixed workflow saved.");
