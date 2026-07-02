const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));
let mergeNode = data.nodes.find(n => n.name === 'Merge');
console.log(JSON.stringify(mergeNode, null, 2));
