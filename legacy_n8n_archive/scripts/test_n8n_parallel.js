const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));

let c = data.connections;
for (let n in c) {
  if (Array.isArray(c[n].main)) {
    c[n].main.forEach((outs, i) => {
      if (outs && outs.length > 1) {
        console.log(`Node '${n}' Output ${i} branches to:`, outs.map(o=>o.node).join(', '));
      }
    });
  }
}
