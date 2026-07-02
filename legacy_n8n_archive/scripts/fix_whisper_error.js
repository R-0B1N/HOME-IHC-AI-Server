const fs = require('fs');

let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));

// 1. Change Download Audio to output binary data into the property named "file" instead of "data"
let downloadAudioNode = data.nodes.find(n => n.name === 'Download Audio');
if (downloadAudioNode) {
    if (!downloadAudioNode.parameters.options) downloadAudioNode.parameters.options = {};
    if (!downloadAudioNode.parameters.options.response) downloadAudioNode.parameters.options.response = {};
    if (!downloadAudioNode.parameters.options.response.response) downloadAudioNode.parameters.options.response.response = {};
    
    downloadAudioNode.parameters.options.response.response.responseFormat = "file";
    downloadAudioNode.parameters.options.response.response.outputPropertyName = "file";
}

// 2. Ensure Transcribe Audio correctly references "file"
let audioNode = data.nodes.find(n => n.name === 'Transcribe Audio');
if (audioNode) {
    audioNode.parameters.sendInputData = true;
    audioNode.parameters.inputDataFieldName = "file";
}

fs.writeFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed2.json', JSON.stringify(data, null, 2));

console.log("Fixed whisper 422 error.");
