const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));
let switchNode = data.nodes.find(n => n.name === 'Input type2');
console.log("Switch Node:", JSON.stringify(switchNode, null, 2));
