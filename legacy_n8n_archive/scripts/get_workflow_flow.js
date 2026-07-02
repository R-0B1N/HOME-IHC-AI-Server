const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28.json', 'utf8'));

// Print connections to see the flow
console.log(JSON.stringify(data.connections, null, 2));
