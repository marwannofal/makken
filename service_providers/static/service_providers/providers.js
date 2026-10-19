(() => {
  'use strict';
  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  const page = $('[data-provider-page]');
  if (!page) return;
  let busy = false, confirmAction = null;
  // Keep native constraint feedback Arabic even in an English browser.
  const nativeMessages=new WeakMap();
  page.addEventListener('invalid',event=>{
    const field=event.target;
    if(!field.setCustomValidity||field.validity.customError)return;
    const message=field.validity.valueMissing?'هذا الحقل مطلوب.':field.validity.typeMismatch?'أدخل قيمة صحيحة لهذا الحقل.':field.validity.tooLong?'القيمة أطول من الحد المسموح.':'راجع قيمة هذا الحقل.';
    field.setCustomValidity(message);nativeMessages.set(field,message);
  },true);
  const clearNative=event=>{const target=event.target;const fields=target.type==='radio'?$$('input[type=radio]',target.form||page).filter(field=>field.name===target.name):[target];fields.forEach(field=>{if(nativeMessages.has(field)&&field.validationMessage===nativeMessages.get(field)){field.setCustomValidity('');nativeMessages.delete(field);}});};
  page.addEventListener('input',clearNative,true);page.addEventListener('change',clearNative,true);
  const dialog = $('#provider-confirm');
  function open(target) {target._providerReturn=document.activeElement;target.showModal();}
  $$('dialog.partnership-dialog').forEach(target=>target.addEventListener('close',()=>{const previous=target._providerReturn;if(previous?.isConnected&&previous.getClientRects().length)previous.focus();}));
  $$('[data-provider-close]').forEach(button=>button.addEventListener('click',()=>{if(!busy)button.closest('dialog')?.close();}));
  function ask(text, action, danger=false) {
    $('[data-provider-confirm-text]').textContent=text;
    const button=$('[data-provider-confirm-yes]');button.classList.toggle('button-danger',danger);button.classList.toggle('button-primary',!danger);
    confirmAction=action;open(dialog);
  }
  $('[data-provider-confirm-yes]')?.addEventListener('click',()=>{const action=confirmAction;confirmAction=null;dialog.close();action?.();});
  dialog?.addEventListener('close',()=>{confirmAction=null;});
  $$('[data-provider-server]').forEach(target=>{target.removeAttribute('open');open(target);});
  if(page.dataset.providerPage==='editor')$$('[data-management-group]').forEach(group=>group.open=true);
  $$('[data-provider-row]').forEach(row=>row.addEventListener('click',event=>{if(!event.target.closest('a,button,form,input,select,label')&&!getSelection()?.toString())location.assign(row.dataset.url);}));
  $$('[data-provider-final]').forEach(form=>form.addEventListener('submit',event=>{if(form.dataset.sent){event.preventDefault();return;}form.dataset.sent='1';$$('button[type=submit]',form).forEach(button=>{button.disabled=true;button.textContent='جارٍ الحفظ…';});}));

  // Rebuilt option buttons must not be mistaken for an outside click.
  $$('.market-select').forEach(wrapper=>wrapper.addEventListener('click',event=>event.stopPropagation()));

  const editor=$('[data-provider-editor]');
  if(editor){
    const catalog=JSON.parse($('#provider-catalog').textContent),region=$('#provider-region'),specs=$('#provider-specializations'),table=$('[data-provider-coverage]'),lineForm=$('[data-provider-coverage-form]'),lineDialog=$('#provider-coverage-editor');
    let drafts=JSON.parse($('#provider-drafts').textContent),editing=-1,coveragePage=1;
    if(!Array.isArray(drafts))drafts=[];
    const valid=drafts.filter(row=>row&&Number.isSafeInteger(row.region)&&Array.isArray(row.specializations)&&row.specializations.every(Number.isSafeInteger)&&typeof row.is_active==='boolean');
    if(valid.length!==drafts.length)$('[data-provider-draft-error]').textContent='توجد بيانات بنود غير صحيحة. راجع المناطق والتخصصات قبل الحفظ.';
    drafts=valid;
    const original=new Map(catalog.original.map(row=>[row.region,new Set(row.specializations)]));
    const make=(tag,cls,text)=>{const element=document.createElement(tag);element.className=cls||'';if(text!==undefined)element.textContent=text;return element;};
    const icon=(path)=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('aria-hidden','true');svg.setAttribute('viewBox','0 0 24 24');const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',path);svg.append(p);return svg;};
    function action(text,path,run,kind=''){const button=make('button','row-action '+kind);button.type='button';button.append(icon(path),make('span','',text));button.addEventListener('click',run);return button;}
    function sync(){ $('#provider-coverage').value=JSON.stringify(drafts); }
    function render(){
      table.replaceChildren();
      const pages=Math.max(1,Math.ceil(drafts.length/10));coveragePage=Math.min(Math.max(1,coveragePage),pages);
      $('[data-provider-coverage-count]').textContent='عدد السجلات: '+drafts.length;
      $('[data-provider-coverage-page]').textContent=coveragePage+' / '+pages;
      $('[data-provider-coverage-previous]').disabled=coveragePage===1;
      $('[data-provider-coverage-next]').disabled=coveragePage===pages;
      drafts.forEach((row,index)=>{
        if(index<(coveragePage-1)*10||index>=coveragePage*10)return;
        const tr=make('tr'),r=make('th','',catalog.regions.find(item=>item.id===row.region)?.name||'منطقة غير متاحة');r.scope='row';
        const selected=make('td');row.specializations.forEach(id=>{const item=catalog.specializations.find(s=>s.id===id);selected.append(make('span','tag',(item?.name||'تخصص غير متاح')+(item&&!item.is_active?' · محفوظ سابقًا':'')));});
        const status=make('td'),toggle=make('button','record-status '+(row.is_active?'is-enabled':'is-disabled'),row.is_active?'نشط':'غير نشط');toggle.type='button';toggle.setAttribute('aria-label','تغيير حالة بند '+r.textContent);toggle.addEventListener('click',()=>ask('تأكيد تغيير حالة هذا البند؟ تُحفظ النتيجة بعد حفظ المزود كاملًا.',()=>{drafts[index].is_active=!drafts[index].is_active;render();}));status.append(toggle);
        const cell=make('td'),actions=make('div','row-actions');actions.append(action('تعديل','m16 4 4 4M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15Z',()=>edit(index)),action('حذف','M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',()=>ask('هل تريد حذف هذا البند من مسودة المزود؟',()=>{drafts.splice(index,1);render();},true),'delete-action'));cell.append(actions);tr.append(r,selected,status,cell);table.append(tr);
      });
      if(!drafts.length){const tr=make('tr'),td=make('td','provider-empty','لم تُضف مناطق بعد. أضف منطقة وتخصصاتها للمتابعة.');td.colSpan=4;tr.append(td);table.append(tr);}
      sync();
    }
    function refreshSpecs(selected=[]){
      const kept=original.get(Number(region.value))||new Set();
      specs.replaceChildren();catalog.specializations.filter(spec=>spec.is_active||kept.has(spec.id)).forEach(spec=>{const option=new Option(spec.name+(spec.sector?' · '+spec.sector:'')+(spec.is_active?'':' (محفوظ سابقًا)'),spec.id);option.selected=selected.includes(spec.id);specs.add(option);});specs.dispatchEvent(new Event('change',{bubbles:true}));
    }
    function edit(index){
      editing=index;const row=index>=0?drafts[index]:null;region.replaceChildren(new Option('اختر المنطقة',''));
      catalog.regions.filter(r=>(r.is_active||r.id===row?.region)&&!drafts.some((draft,i)=>i!==index&&draft.region===r.id)).forEach(r=>region.add(new Option(r.name+(r.is_active?'':' (محفوظ سابقًا)'),r.id)));
      region.value=String(row?.region||'');region.dispatchEvent(new Event('change',{bubbles:true}));refreshSpecs(row?.specializations||[]);
      $(`input[name=coverage_active][value="${row?.is_active===false?'0':'1'}"]`).checked=true;
      $('#coverage-editor-title').textContent=row?'تعديل منطقة وتخصصات المزود':'إضافة منطقة وتخصصات المزود';$('[data-provider-line-error]').textContent='';open(lineDialog);
    }
    region.addEventListener('change',()=>refreshSpecs());
    $('[data-provider-add]').addEventListener('click',()=>edit(-1));
    lineForm.addEventListener('submit',event=>{
      event.preventDefault();if(!lineForm.reportValidity())return;
      const value={region:Number(region.value),specializations:[...specs.selectedOptions].map(option=>Number(option.value)).sort((a,b)=>a-b),is_active:$('input[name=coverage_active]:checked').value==='1'};
      if(!value.region||!value.specializations.length||drafts.some((row,i)=>i!==editing&&row.region===value.region)){$('[data-provider-line-error]').textContent='اختر منطقة غير مكررة وتخصصًا واحدًا على الأقل.';return;}
      ask('تأكيد حفظ المنطقة والتخصصات في مسودة المزود؟',()=>{if(editing<0){drafts.push(value);coveragePage=Math.ceil(drafts.length/10);}else drafts[editing]=value;lineDialog.close();render();});
    });
    editor.addEventListener('submit',event=>{sync();if(!drafts.length){event.preventDefault();$('[data-provider-draft-error]').textContent='أضف منطقة واحدة على الأقل واختر تخصصاتها.';$('[data-provider-add]').focus();}});
    $('[data-provider-coverage-previous]').addEventListener('click',()=>{coveragePage--;render();});
    $('[data-provider-coverage-next]').addEventListener('click',()=>{coveragePage++;render();});
    render();
  }

  const conversion=$('[data-provider-conversion]');
  if(conversion){
    const files=$('#conversion-attachments'),fileList=$('[data-provider-selected-files]');
    files.addEventListener('change',()=>{
      fileList.replaceChildren();files.setCustomValidity('');
      if(files.files.length>20)files.setCustomValidity('يمكن اختيار 20 مرفقًا كحد أقصى.');
      for(const file of files.files){
        const row=document.createElement('div'),name=document.createElement('span'),size=document.createElement('small');
        name.textContent=file.name;size.textContent=(file.size/1024/1024).toFixed(2)+' MiB';name.append(size);row.append(name);fileList.append(row);
        if(!file.size||file.size>100*1024*1024||!/[.](pdf|png|jpe?g)$/i.test(file.name))files.setCustomValidity('اختر ملفات PDF أو PNG أو JPG أو JPEG غير فارغة، وبحد 100 MiB لكل ملف.');
      }
    });
    conversion.addEventListener('click',event=>{if(busy&&event.target.closest('a')){event.preventDefault();$('[data-provider-upload-status]').textContent='جارٍ التحقق والحفظ. انتظر اكتمال العملية قبل مغادرة الصفحة.';}},true);
    const money=$('#conversion-financial_capacity');
    let moneyDisplay=money.value,moneyEditing=false,moneyError='';
    money.addEventListener('beforeinput',event=>{moneyEditing=money.value===moneyDisplay&&!/paste|drop|replacement/i.test(event.inputType||'')&&!/[٬,]/.test(event.data||'');});
    function formatMoney(){
      const value=money.value.trim().replace(/[٠-٩۰-۹]/g,c=>String(c.charCodeAt(0)-(c<='٩'?1632:1776))).replace(/٬/g,',').replace(/٫/g,'.');
      const grouping=!value.includes(',')||moneyEditing||/^\d{1,3}(?:,\d{3})+(?:\.\d{0,2})?$/.test(value);
      moneyEditing=false;
      if(!value){if(money.validationMessage===moneyError)money.setCustomValidity('');moneyError='';moneyDisplay='';return;}
      const raw=value.replace(/,/g,'');
      if(!grouping||!/^\d+(?:\.\d{0,2})?$/.test(raw)){moneyError='أدخل مبلغًا صحيحًا بفواصل آلاف صحيحة ومنزلتين عشريتين كحد أقصى.';money.setCustomValidity(moneyError);return;}
      if(money.validationMessage===moneyError)money.setCustomValidity('');moneyError='';
      const position=money.selectionStart,offset=position===null?null:money.value.slice(0,position).replace(/[٬,]/g,'').length;
      const [whole,part]=raw.split('.');moneyDisplay=whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+(part===undefined?'':'.'+part);money.value=moneyDisplay;
      if(offset!==null&&document.activeElement===money){let cursor=0,seen=0;while(cursor<moneyDisplay.length&&seen<offset){if(moneyDisplay[cursor]!==',')seen++;cursor++;}money.setSelectionRange(cursor,cursor);}
    }
    money.addEventListener('input',formatMoney);formatMoney();
    conversion.addEventListener('submit',event=>{event.preventDefault();if(busy||!conversion.reportValidity())return;ask('سيتم إنشاء جهة بحالة رغبة، وربطها بالمزود وحفظ الاتفاق والمرفقات الخاصة. هل تريد المتابعة؟',()=>{
      const body=new FormData(conversion),error=$('[data-provider-upload-error]'),area=$('[data-provider-upload-progress]'),bar=$('progress',area),status=$('[data-provider-upload-status]'),submit=$('[data-provider-convert-submit]');
      busy=true;area.hidden=false;error.hidden=true;bar.value=0;status.textContent='جارٍ رفع المرفقات…';conversion.setAttribute('aria-busy','true');const disabled=$$('button,input,select,textarea',conversion).map(node=>({node,previous:node.disabled}));disabled.forEach(({node})=>node.disabled=true);
      const xhr=new XMLHttpRequest();xhr.open('POST',conversion.action);xhr.setRequestHeader('X-Requested-With','XMLHttpRequest');xhr.timeout=600000;
      xhr.upload.addEventListener('progress',e=>{if(e.lengthComputable){bar.value=Math.floor(e.loaded/e.total*100);status.textContent=bar.value<100?'جارٍ رفع المرفقات: '+bar.value+'%':'اكتمل الإرسال؛ جارٍ التحقق والحفظ…';}});
      function unlock(message){busy=false;conversion.removeAttribute('aria-busy');disabled.forEach(({node,previous})=>node.disabled=previous);error.hidden=false;error.textContent=message;status.textContent='لم تكتمل العملية. راجع الرسالة قبل تكرارها.';}
      xhr.addEventListener('load',()=>{let result;try{result=JSON.parse(xhr.responseText);}catch{}if(xhr.status>=200&&xhr.status<300&&result?.redirect){location.assign(result.redirect);return;}unlock([result?.error||'تعذّر التحويل. حدّث الصفحة للتحقق من النتيجة.',...Object.values(result?.fields||{}).flat().map(row=>row.message)].join(' '));});
      xhr.addEventListener('error',()=>unlock('انقطع الاتصال. حدّث السجل للتأكد من النتيجة قبل إعادة التحويل.'));xhr.addEventListener('timeout',()=>unlock('انتهت مهلة الاتصال. تحقق من السجل قبل تكرار الطلب.'));xhr.send(body);
    });});
    $('#provider-conversion').addEventListener('cancel',event=>{event.preventDefault();if(!busy)location.assign(event.currentTarget.dataset.closeUrl);});
  }
})();
