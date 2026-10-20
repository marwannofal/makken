(() => {
  'use strict';
  const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
  const dialog=$('#ac-confirm'),feedback=$('#ac-feedback');let pending=null,opener=null,busy=false;
  const show=d=>{opener=document.activeElement;if(!d.open)d.showModal();};
  const message=text=>{$('[data-ac-feedback-message]').textContent=text;show(feedback);};
  $$('[data-ac-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  [dialog,feedback].filter(Boolean).forEach(d=>d.addEventListener('close',()=>{if(opener?.isConnected)opener.focus();}));
  async function submit(form){
    if(form.hasAttribute('data-ac-ajax')){
      if(busy)return;busy=true;const buttons=$$('button',form);buttons.forEach(b=>b.disabled=true);
      try{
        const response=await fetch(form.action,{method:'POST',body:new FormData(form),credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
        const data=await response.json().catch(()=>({error:'تعذّر إتمام العملية. حدّث الصفحة وحاول مجددًا.'}));
        if(!response.ok){message(data.error||'تعذّر إتمام العملية.');return;}
        if(data.redirect)location.assign(data.redirect);else message(data.message||'تم الحفظ.');
      }catch{message('تعذّر الاتصال بالخادم. تحقق من اتصالك ثم حاول مجددًا.');}
      finally{busy=false;buttons.forEach(b=>b.disabled=false);}
    }else{
      form.dataset.confirmed='1';form.dataset.clean='1';form.requestSubmit();
    }
  }
  $$('form[data-ac-confirm]').forEach(form=>form.addEventListener('submit',event=>{
    if(form.dataset.confirmed==='1'){$$('button[type=submit]',form).forEach(button=>{button.disabled=true;button.textContent='جار الحفظ…';});return;}
    event.preventDefault();if(!form.reportValidity())return;
    pending=form;$('[data-ac-message]').textContent=form.dataset.acConfirm;show(dialog);
  }));
  $('[data-ac-yes]')?.addEventListener('click',()=>{const form=pending;pending=null;dialog.close();if(form)submit(form);});
  $$('form[data-ac-dirty]').forEach(form=>{let changed=false;form.addEventListener('input',()=>changed=true);form.addEventListener('change',()=>changed=true);window.addEventListener('beforeunload',event=>{if(changed&&form.dataset.clean!=='1'){event.preventDefault();event.returnValue='';}});});
  const editor=$('[data-user-editor]'),catalog=$('#ac-role-catalog')?JSON.parse($('#ac-role-catalog').textContent):[];
  function preview(){
    if(!editor)return;
    const roles=new Set([...editor.elements.roles.selectedOptions].map(option=>Number(option.value)));
    const scope=editor.elements.page_scope.value,pages=new Set([...editor.elements.allowed_pages.selectedOptions].map(option=>option.value));
    const grants=new Map();
    catalog.filter(role=>roles.has(role.id)).forEach(role=>role.permissions.forEach(key=>{
      const [module]=key.split(':');if(role.scope==='selected'&&!role.pages.includes(module))return;
      if(!grants.has(key))grants.set(key,[]);grants.get(key).push('دور: '+role.name);
    }));
    const decide=(module,op)=>{
      if(editor.elements.is_active.value==='0')return [false,'الحساب غير نشط'];
      if(editor.dataset.superuser==='1')return [true,'مدير النظام الأعلى'];
      if(scope==='selected'&&!pages.has(module))return [false,'خارج الصفحات المحددة'];
      const field=editor.elements.namedItem('override__'+module+'__'+op),value=field?.value||'inherit';
      if(value==='deny')return [false,'منع صريح للمستخدم'];
      if(op!=='view'&&!decide(module,'view')[0])return [false,'صلاحية العرض مطلوبة'];
      if(value==='grant')return [true,'منح مباشر'];
      const sources=grants.get(module+':'+op)||[];return [sources.length>0,sources.join(' + ')||'لم تُمنح الصلاحية'];
    };
    $$('[data-ac-module]',editor).forEach(row=>$$('[data-ac-op]',row).forEach(cell=>{
      const output=$('[data-ac-effective]',cell);if(!output)return;
      const [allowed,source]=decide(row.dataset.acModule,cell.dataset.acOp);output.textContent=allowed?'مسموح':'غير مسموح';output.classList.toggle('is-granted',allowed);$('[data-ac-source]',cell).textContent=source;
    }));
  }
  $$('[data-ac-column]').forEach(button=>button.addEventListener('click',()=>{
    const op=button.dataset.acColumn,matrix=$('[data-ac-matrix]'),role=matrix.hasAttribute('data-role-matrix');
    $$('[data-ac-op="'+op+'"]',matrix).forEach(cell=>{const field=$(role?'input[type=checkbox]':'select',cell);if(field){if(role)field.checked=true;else field.value='grant';}});
    if(op!=='view')$$('[data-ac-op="view"]',matrix).forEach(cell=>{const field=$(role?'input[type=checkbox]':'select',cell);if(field){if(role)field.checked=true;else field.value='grant';}});
    matrix.dispatchEvent(new Event('change',{bubbles:true}));preview();
  }));
  $('[data-ac-clear]')?.addEventListener('click',()=>{const matrix=$('[data-ac-matrix]');$$('input[type=checkbox]',matrix).forEach(field=>field.checked=false);$$('select',matrix).forEach(field=>field.value='inherit');matrix.dispatchEvent(new Event('change',{bubbles:true}));preview();});
  $$('[name=page_scope]').forEach(field=>{const update=()=>{const section=$('[data-ac-pages]');if(section)section.hidden=field.value!=='selected';preview();};field.addEventListener('change',update);update();});
  editor?.addEventListener('change',preview);preview();
  document.addEventListener('invalid',event=>{const field=event.target;if(!field.closest('.ac-workspace')||!field.setCustomValidity||field.validity.customError)return;field.setCustomValidity(field.validity.valueMissing?'هذا الحقل مطلوب.':field.validity.typeMismatch?'أدخل قيمة صحيحة لهذا الحقل.':'راجع قيمة هذا الحقل.');},true);
  document.addEventListener('input',event=>{if(event.target.closest('.ac-workspace')&&event.target.setCustomValidity)event.target.setCustomValidity('');},true);
})();
