(() => {
  'use strict';
  const form=document.querySelector('[data-dashboard-filters]');
  if(form){
    const period=form.querySelector('[name=period]'),range=form.querySelector('[data-date-range]');
    function syncPeriod(){const custom=period.value==='custom';range.hidden=!custom;range.querySelectorAll('input').forEach(n=>n.disabled=!custom);}
    period.addEventListener('change',syncPeriod);syncPeriod();
    const sector=form.querySelector('[name=sector]'),spec=form.querySelector('[name=specialization]');
    let pairs=[];try{pairs=JSON.parse(document.getElementById('dashboard-pairs').textContent);}catch{}
    function syncSpec(){const allowed=new Set(pairs.filter(p=>!sector.value||String(p[0])===sector.value).map(p=>String(p[1])));let reset=false;[...spec.options].forEach(o=>{o.hidden=!!o.value&&!allowed.has(o.value);if(o.hidden&&o.selected){o.selected=false;reset=true;}});if(reset){spec.value='';document.querySelector('[data-filter-message]').textContent='تم مسح التخصص السابق لعدم ارتباطه بالقطاع المختار.';}spec.dispatchEvent(new Event('change',{bubbles:true}));}
    sector.addEventListener('change',syncSpec);syncSpec();
    form.addEventListener('submit',()=>{if(form.checkValidity()){form.setAttribute('aria-busy','true');const button=form.querySelector('button[type=submit]');button.textContent='جار تحديث اللوحة…';button.disabled=true;}});
  }
  document.querySelectorAll('[data-dashboard-export]').forEach(button=>button.addEventListener('click',()=>{
    window.MakkenTableExports?.downloadUrl(button,button.dataset.dashboardExport);
  }));
  const dialog=document.getElementById('dash-chart-dialog');if(!dialog)return;
  let opener=null;
  document.querySelectorAll('[data-chart-open]').forEach(button=>button.addEventListener('click',()=>{
    const source=document.getElementById('dash-chart-'+button.dataset.chartOpen);if(!source)return;
    opener=button;dialog.querySelector('[data-chart-content]').replaceChildren(source.content.cloneNode(true));dialog.showModal();
  }));
  dialog.querySelector('[data-chart-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{if(opener?.isConnected)opener.focus();});
})();
