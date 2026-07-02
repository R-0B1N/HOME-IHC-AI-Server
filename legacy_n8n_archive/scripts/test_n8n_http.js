const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));
let dlNode = data.nodes.find(n => n.name === 'Download Audio');
console.log(JSON.stringify(dlNode, null, 2));
