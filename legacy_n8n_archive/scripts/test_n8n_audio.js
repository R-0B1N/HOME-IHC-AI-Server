const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));
let audioNode = data.nodes.find(n => n.name === 'Audio');
let aiNode = data.nodes.find(n => n.name === 'AI Agent - Admin');
console.log("Audio Node:", JSON.stringify(audioNode, null, 2));
console.log("AI Node:", JSON.stringify(aiNode, null, 2));
