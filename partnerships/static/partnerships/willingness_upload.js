(() => {
  'use strict';
  const form = document.querySelector('[data-willingness-form]');
  if (!form) return;
  const input = form.querySelector('#willingness-files');
  const list = form.querySelector('[data-selected-files]');
  const error = form.querySelector('[data-upload-error]');
  const panel = form.querySelector('[data-upload-progress]');
  const progress = panel.querySelector('progress');
  const percentage = panel.querySelector('[data-upload-percent]');
  const status = panel.querySelector('[data-upload-status]');
  const dialog = form.closest('dialog');
  const submit = form.querySelector('button[type=submit]');
  let files = [], busy = false;
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function fileSize(size) {
    return size < 1024*1024 ? (size/1024).toFixed(1)+' KB' : (size/(1024*1024)).toFixed(1)+' MB';
  }
  function updateFiles() {
    const transfer = new DataTransfer();
    files.forEach(file=>transfer.items.add(file));
    input.files = transfer.files;
    list.replaceChildren();
    files.forEach((file,index)=>{
      const row = make('li');
      row.append(make('span','willingness-queue-icon',file.name.split('.').pop().toUpperCase()));
      const info = make('div','willingness-queue-info');
      info.append(make('bdi','',file.name),make('small','',fileSize(file.size)+' · جاهز للرفع'));
      const remove = make('button','willingness-file-remove','×');
      remove.type='button';remove.setAttribute('aria-label','إزالة '+file.name);
      remove.addEventListener('click',()=>{files.splice(index,1);updateFiles();});
      row.append(info,remove);list.append(row);
    });
  }
  input.addEventListener('change',()=>{
    error.textContent='';panel.hidden=true;form.querySelector('#attachments-errors').replaceChildren();
    const added=[...input.files];
    for(const file of added) {
      if(!/\.(pdf|png|jpe?g)$/i.test(file.name) || !file.size || file.size>100*1024*1024) {
        error.textContent='اختر ملفات PDF أو PNG أو JPG أو JPEG غير فارغة، حتى 100 MB لكل ملف.';
        updateFiles();return;
      }
    }
    const merged = [...files];
    added.forEach(file=>{if(!merged.some(old=>old.name===file.name&&old.size===file.size&&old.lastModified===file.lastModified))merged.push(file);});
    if(merged.length>20) {error.textContent='يمكن رفع 20 مرفقًا كحد أقصى.';updateFiles();return;}
    files=merged;updateFiles();
  });
  form.querySelector('#willingness-agreement').addEventListener('change',()=>form.querySelector('#agreement-errors').replaceChildren());
  function setBusy(value) {
    busy=value;dialog.setAttribute('aria-busy',String(value));
    form.querySelectorAll('button,input,select').forEach(control=>control.disabled=value);
    dialog.querySelectorAll('[data-dismiss-dialog]').forEach(control=>control.disabled=value);
    submit.textContent=value?'جار الرفع والحفظ…':'حفظ والتحويل إلى رغبة';
  }
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  form.addEventListener('submit',event=>{
    event.preventDefault();
    if(busy || !form.reportValidity())return;
    error.textContent='';
    form.querySelectorAll('#agreement-errors,#attachments-errors').forEach(node=>node.replaceChildren());
    const body=new FormData(form); // Capture enabled file controls before locking them.
    setBusy(true);list.querySelectorAll('.willingness-queue-info small').forEach((node,index)=>node.textContent=fileSize(files[index].size)+' · قيد الرفع');panel.hidden=false;progress.value=0;percentage.textContent='0%';status.textContent='جار رفع المرفقات…';
    const xhr=new XMLHttpRequest();
    xhr.upload.addEventListener('progress',event=>{
      if(event.lengthComputable){const value=Math.floor(event.loaded/event.total*100);progress.value=value;percentage.textContent=value+'%';}
    });
    xhr.upload.addEventListener('load',()=>{progress.value=100;percentage.textContent='100%';status.textContent='اكتمل إرسال الملفات — جار التحقق والحفظ…';list.querySelectorAll('.willingness-queue-info small').forEach((node,index)=>node.textContent=fileSize(files[index].size)+' · قيد التحقق والحفظ');});
    function fail(message) {setBusy(false);status.textContent='لم يكتمل تأكيد الحفظ';error.textContent=message;}
    xhr.addEventListener('load',()=>{
      let result;
      try {result=JSON.parse(xhr.responseText);} catch {
        fail(xhr.status===413?'حجم الطلب يتجاوز إعدادات الخادم. تواصل مع مسؤول النظام لرفع الحد.':'تعذّر تأكيد النتيجة. حدّث السجل وتحقق من الحالة قبل إعادة المحاولة.');return;
      }
      if(xhr.status>=200&&xhr.status<300&&result.redirect){
        status.textContent='تم رفع المرفقات وحفظ التحويل إلى رغبة بنجاح.';
        progress.value=100;percentage.textContent='100%';
        location.assign(result.redirect);return;
      }
      for(const [field,items] of Object.entries(result.errors||{})){
        const node=form.querySelector(field==='agreement_type'?'#agreement-errors':field==='attachments'?'#attachments-errors':'[data-upload-error]');
        if(node)node.textContent=items.map(item=>item.message).join(' ');
      }
      fail(result.error||'تعذّر حفظ التحويل. راجع البيانات وحاول مرة أخرى.');
    });
    xhr.addEventListener('error',()=>fail('انقطع الاتصال. حدّث السجل وتحقق من حالة الجهة قبل إعادة المحاولة.'));
    xhr.addEventListener('timeout',()=>fail('انتهت مهلة الاتصال. حدّث السجل وتحقق من النتيجة قبل إعادة المحاولة.'));
    xhr.open('POST',form.getAttribute('action')||location.href);
    xhr.setRequestHeader('X-Requested-With','XMLHttpRequest');
    xhr.timeout=15*60*1000;
    xhr.send(body);
  });
})();
