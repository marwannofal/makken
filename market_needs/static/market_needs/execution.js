(() => {
  'use strict';
  const page = document.querySelector('[data-execution-page]');
  if (!page) return;
  const form = page.querySelector('[data-execution-editor]');
  const hidden = form.querySelector('[name=selection]');
  const key = page.dataset.draftKey;
  const status = form.querySelector('[name=status]');
  const notes = form.querySelector('[name=notes]');
  const original = {selection:hidden.value,status:status?.value,notes:notes?.value};
  try {original.selection=JSON.stringify(JSON.parse(original.selection));} catch {}
  let draft;
  try {draft = JSON.parse(hidden.value);} catch {draft = {providers:[],employers:[]};}
  if (!draft || !Array.isArray(draft.providers) || !Array.isArray(draft.employers)) draft = {providers:[],employers:[]};
  let labels = {};
  try {labels=JSON.parse(document.getElementById('execution-labels').textContent);}catch{}
  if (page.dataset.posted !== '1') {
    try {const saved=JSON.parse(sessionStorage.getItem(key));if(saved?.selection&&Array.isArray(saved.selection.providers)&&Array.isArray(saved.selection.employers)){draft=saved.selection;labels={...labels,...(saved.labels||{})};if(status&&saved.status)status.value=saved.status;if(notes)notes.value=saved.notes||'';}} catch {}
  }
  const writable = !!form.querySelector('button[type=submit]');
  if (!writable) {try {draft=JSON.parse(original.selection);}catch{}}
  const persist=()=>{if(!writable)return;try{sessionStorage.setItem(key,JSON.stringify({selection:draft,labels,status:status?.value,notes:notes?.value}));}catch{}};
  function render() {
    hidden.value=JSON.stringify(draft);
    const holder=page.querySelector('[data-execution-selection]');holder.replaceChildren();
    for(const kind of ['providers','employers']) {
      const values=new Set(draft[kind]);
      page.querySelectorAll(`[data-execution-select="${kind}"]`).forEach(box=>{box.checked=values.has(Number(box.value));const row=box.closest('tr');labels[kind+'.'+box.value]=row.querySelector('th a')?.textContent.trim()||box.value;});
      for(const id of values){const button=document.createElement('button');button.type='button';button.disabled=!writable;button.textContent=(kind==='providers'?'مزود تدريب: ':'جهة توظيف: ')+(labels[kind+'.'+id]||'#'+id)+(writable?' ×':'');button.setAttribute('aria-label','إزالة '+button.textContent);button.addEventListener('click',()=>{draft[kind]=draft[kind].filter(value=>value!==id);render();});holder.append(button);}
    }
    page.querySelector('[data-execution-selection-count]').textContent='اختيارات المسودة — مزودو التدريب: '+draft.providers.length+'، جهات التوظيف: '+draft.employers.length;
    persist();
  }
  page.querySelectorAll('[data-execution-select]').forEach(box=>box.addEventListener('change',()=>{const kind=box.dataset.executionSelect,id=Number(box.value);draft[kind]=box.checked?[...new Set([...draft[kind],id])]:draft[kind].filter(value=>value!==id);render();}));
  status?.addEventListener('change',persist);notes?.addEventListener('input',persist);
  const show=dialog=>{if(!dialog.open){dialog._marketReturn=document.activeElement;dialog.showModal();}};
  page.querySelectorAll('[data-execution-dialog]').forEach(control=>control.addEventListener('click',event=>{if(control.tagName==='TR'&&event.target.closest('button,a,input,select,label'))return;show(document.getElementById(control.dataset.executionDialog));}));
  const dirty=()=>writable&&(JSON.stringify(draft)!==original.selection||status?.value!==original.status||notes?.value!==original.notes);
  document.querySelectorAll('[data-execution-leave]').forEach(link=>link.addEventListener('click',event=>{if(!dirty()){try{sessionStorage.removeItem(key);}catch{}return;}event.preventDefault();const dialog=document.getElementById('execution-discard'),yes=dialog.querySelector('[data-execution-discard-yes]');yes.href=link.href;yes.onclick=()=>{try{sessionStorage.removeItem(key);}catch{}};show(dialog);}));
  page.querySelector('[data-execution-reset]')?.addEventListener('click',()=>{const dialog=document.getElementById('execution-discard'),yes=dialog.querySelector('[data-execution-discard-yes]');yes.href=window.location.pathname;yes.onclick=()=>{try{sessionStorage.removeItem(key);}catch{}};show(dialog);});
  form.addEventListener('submit',()=>{hidden.value=JSON.stringify(draft);persist();});
  page.querySelectorAll('[data-execution-final]').forEach(final=>final.addEventListener('submit',event=>{if(final.dataset.sent){event.preventDefault();return;}final.dataset.sent='1';final.querySelectorAll('button[type=submit]').forEach(button=>{button.disabled=true;button.textContent='جار الحفظ…';});}));
  render();
})();
