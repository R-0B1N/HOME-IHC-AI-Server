const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));

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
                    "value": "base",
                    "parameterType": "string"
                },
                {
                    "name": "response_format",
                    "value": "json",
                    "parameterType": "string"
                },
                {
                    "name": "file",
                    "inputDataFieldName": "data",
                    "parameterType": "formBinaryData"
                }
            ]
        },
        "options": {}
    };
    delete audioNode.parameters.sendInputData;
    delete audioNode.parameters.inputDataFieldName;
}

fs.writeFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed3.json', JSON.stringify(data, null, 2));
console.log("Fixed with formBinaryData.");
