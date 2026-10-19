(() => {
  'use strict';
  const node=document.getElementById('makken-operation-access');if(!node)return;
  const access=JSON.parse(node.textContent);
  // Backend templates handle static controls. This covers existing JS-created
  // owned-row controls, whose removal/status changes are separately checked.
  function update(){
    if(!access.delete)document.querySelectorAll('[data-provider-editor] .delete-action,[data-partnership-form] .delete-action').forEach(button=>{button.hidden=true;});
    if(!access.change_status)document.querySelectorAll('[data-provider-editor] button.record-status,[data-partnership-form] button.record-status').forEach(button=>{button.disabled=true;button.setAttribute('aria-disabled','true');});
  }
  document.addEventListener('submit',event=>{event.target.querySelectorAll?.('input[data-ac-locked-status]').forEach(hidden=>{const current=event.target.querySelector('input[type=radio][name="'+CSS.escape(hidden.name)+'"]:checked');if(current)hidden.value=current.value;});},true);
  update();let queued=false;
  new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;update();});}).observe(document.getElementById('main-content')||document.body,{childList:true,subtree:true});
})();
