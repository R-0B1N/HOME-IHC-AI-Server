const fs = require('fs');
let data = JSON.parse(fs.readFileSync('/Users/nick/Work/HOME IHC/Whatsapp AI/workflow_kgNpbEYnHVtMnF28_fixed.json', 'utf8'));

let connections = data.connections;
for (let nodeName in connections) {
  let mainOutputs = connections[nodeName].main;
  if (Array.isArray(mainOutputs)) {
    mainOutputs.forEach((outputList, index) => {
      if (Array.isArray(outputList) && outputList.length > 0) {
        console.log(`Node '${nodeName}' Output ${index} ->`, outputList.map(o => o.node).join(', '));
      }
    });
  }
}
