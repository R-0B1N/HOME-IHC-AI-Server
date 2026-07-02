const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28.json', 'utf8'));

let audioNode = data.nodes.find(n => n.name === 'Transcribe Audio');
console.log(JSON.stringify(audioNode, null, 2));
