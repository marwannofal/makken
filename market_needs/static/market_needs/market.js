(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const make = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls || ''; if (text !== undefined) n.textContent = text; return n; };
  const normal = s => String(s).normalize('NFKC').toLocaleLowerCase().replace(/[\u064b-\u065f\u0670]/g, '');
  const show = d => { if (d && !d.open) {const current=document.activeElement;d._marketReturn=current?.closest('.market-select')?.querySelector('.market-select-trigger')||current;d.showModal();} };
  $$('dialog.partnership-dialog').forEach(d=>d.addEventListener('close',()=>{const previous=d._marketReturn;if(previous?.isConnected&&previous.getClientRects().length&&!previous.disabled&&!previous.matches('.native-enhanced'))previous.focus({preventScroll:true});else $('#main-content')?.focus({preventScroll:true});}));
  let busy = false, confirmationCancel = null;
  $$('[data-market-close]').forEach(b => b.addEventListener('click', () => {if (!busy) {const dialog=b.closest('dialog');if(dialog.id==='market-confirm'){const cancel=confirmationCancel;confirmationCancel=null;confirmationAction=null;cancel?.();}dialog.close();}}));
  $$('[data-market-server]').forEach(d => {d.removeAttribute('open');show(d);if(d.dataset.closeUrl)d.addEventListener('cancel', e=>{e.preventDefault();location.assign(d.dataset.closeUrl);});});
  $$('[data-market-row]').forEach(row=>row.addEventListener('click',e=>{if(!e.target.closest('a,button,input,select,label,form')&&!getSelection()?.toString())location.assign(row.dataset.url);}));
  const confirmation = $('#market-confirm');
  let confirmationAction = null;
  function ask(text, callback, danger=false, cancel=null) {
    if (!confirmation) return;
    $('[data-confirm-text]',confirmation).textContent = text;
    $('#market-confirm-title').textContent = danger ? 'تأكيد الحذف / الرفض' : 'تأكيد العملية';
    $('[data-confirm-yes]',confirmation).classList.toggle('button-danger',danger);
    $('[data-confirm-yes]',confirmation).classList.toggle('button-primary',!danger);
    confirmationAction = callback;
    confirmationCancel = cancel;
    confirmation.onclose = () => {const canceled=confirmationCancel;confirmationCancel=null;if (confirmationAction) canceled?.();confirmationAction=null;};
    show(confirmation);
  }
  $('[data-confirm-yes]')?.addEventListener('click',()=>{const run=confirmationAction;confirmationAction=null;confirmationCancel=null;confirmation.close();run?.();});

  // Native selects remain the source of submitted values and validation.
  let sequence=0, opened=null;
  const controls=new Map();
  function enhance(select) {
    if(controls.has(select)) return controls.get(select);
    const wrapper=make('div','search-select market-select'), trigger=make('button','search-select-trigger market-select-trigger'), summary=make('span'),panel=make('div','search-select-panel'),search=make('input'),options=make('div','search-select-options'),tags=make('div','selected-summary'),error=make('p','field-error');
    select.after(wrapper);wrapper.append(trigger,panel,tags,error);trigger.type='button';trigger.append(summary);panel.hidden=true;panel.id='market-select-'+(++sequence);trigger.setAttribute('aria-controls',panel.id);trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-haspopup','true');
    const label=select.labels[0]?.textContent.trim()||select.dataset.label||'الاختيارات';trigger.setAttribute('aria-label',label);search.type='search';search.placeholder='ابحث هنا…';search.autocomplete='off';search.setAttribute('aria-label','البحث في '+label);options.setAttribute('role','group');options.setAttribute('aria-label',label);panel.append(search,options);error.setAttribute('role','alert');select.classList.add('native-enhanced');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    select.labels[0]?.addEventListener('click',e=>{e.preventDefault();trigger.focus();});
    function close(){panel.hidden=true;trigger.setAttribute('aria-expanded','false');if(opened===control)opened=null;}
    function filter(){const term=normal(search.value);$$('[data-option]',options).forEach(n=>n.hidden=!normal(n.textContent).includes(term));let empty=$('.market-select-options-empty',options);if(empty)empty.remove();if(!$$('[data-option]',options).some(n=>!n.hidden))options.append(make('p','market-select-options-empty','لا توجد خيارات مطابقة.'));}
    function update(){options.replaceChildren();[...select.options].filter(o=>o.value&&!o.hidden&&!o.disabled).forEach(option=>{const b=make('button','search-select-option',(select.multiple?(option.selected?'☑ ':'☐ '):'')+option.textContent);b.type='button';b.dataset.option=option.value;b.setAttribute('aria-pressed',String(option.selected));b.addEventListener('click',()=>{if(select.multiple)option.selected=!option.selected;else select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));error.textContent='';update();if(!select.multiple){close();trigger.focus();}else $('[data-option="'+option.value+'"]',options)?.focus();});options.append(b);});const chosen=[...select.selectedOptions].filter(o=>o.value);summary.textContent=select.multiple?(chosen.length?chosen.length+' اختيار محدد':'اختر من القائمة'):(chosen[0]?.textContent||'اختر من القائمة');tags.textContent=select.multiple?chosen.map(o=>o.textContent).join('، '):'';trigger.disabled=select.disabled||select.dataset.marketLocked==='1';filter();}
    function position(){if(!select.closest('.market-edit-lines'))return;const r=trigger.getBoundingClientRect();panel.style.width=r.width+'px';panel.style.left=Math.min(r.left,innerWidth-r.width-20)+'px';panel.style.top=Math.min(r.bottom+5,innerHeight-260)+'px';}
    const control={update,close,trigger};controls.set(select,control);trigger.addEventListener('click',()=>{if(!panel.hidden){close();return;}opened?.close();panel.hidden=false;position();trigger.setAttribute('aria-expanded','true');opened=control;search.value='';filter();search.focus();});search.addEventListener('input',filter);trigger.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();if(panel.hidden)trigger.click();else search.focus();}});wrapper.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();e.stopPropagation();close();trigger.focus();}if(!panel.hidden&&['ArrowDown','ArrowUp','Home','End'].includes(e.key)){const buttons=$$('[data-option]',options).filter(b=>!b.hidden);if(!buttons.length||e.target===search&&['Home','End'].includes(e.key))return;e.preventDefault();let i=buttons.indexOf(document.activeElement);i=e.key==='Home'?0:e.key==='End'?buttons.length-1:(i+(e.key==='ArrowUp'?-1:1)+buttons.length)%buttons.length;buttons[i].focus();}});select.addEventListener('change',update);select.addEventListener('invalid',e=>{e.preventDefault();error.textContent='اختر قيمة متاحة من القائمة.';trigger.focus();});update();return control;
  }
  $$('[data-market-select]').forEach(enhance);
  document.addEventListener('click',e=>{if(!e.target.closest('.market-select'))opened?.close();});
  document.addEventListener('focusin',e=>{if(!e.target.closest('.market-select'))opened?.close();});
  window.addEventListener('resize',()=>opened?.close());
  document.addEventListener('scroll',e=>{if(opened&&opened.trigger.closest('.market-edit-lines')&&!e.target.closest?.('.search-select-panel'))opened.close();},true);

  const editor=$('[data-need-editor]');
  const formatter=new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const decimal=s=>{let v=String(s||'').trim().replace(/[٠-٩۰-۹]/g,c=>String(c.charCodeAt(0)-(c<='٩'?1632:1776))).replaceAll('٬',',').replace('٫','.');if(v.includes(',')&&!/^\d{1,3}(?:,\d{3})+(?:\.\d+)?$/.test(v))return '';return v.replaceAll(',','');};
  // Integer cents avoid binary floating-point errors in client previews.
  const cents=s=>{const v=decimal(s);if(!/^\d+(\.\d{1,2})?$/.test(v))return null;const [whole,fraction='']=v.split('.');return BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));};
  const amount=n=>n===null?'':(n/100n).toString()+'.'+(n%100n).toString().padStart(2,'0');
  let syncEditor=()=>true;
  if(editor){
    const catalog=JSON.parse($('#market-catalog').textContent), sector=$('#id_sector'),spec=$('#id_specialization'),program=$('#id_program'),hidden=$('#id_lines'),tbody=$('[data-expense-rows]');
    let drafts=[];try{drafts=JSON.parse(hidden.value);}catch{}if(!Array.isArray(drafts))drafts=[];
    let previousSector=sector.value,previousProgram=program.value;
    function filterSpecs(){const current=spec.value;spec.replaceChildren(new Option('اختر التخصص',''));catalog.specializations.filter(s=>String(s.sector_id)===sector.value).forEach(s=>spec.add(new Option(s.name+(s.is_active?'':' (غير نشط — محفوظ سابقًا)'),s.id)));spec.value=[...spec.options].some(o=>o.value===current)?current:'';controls.get(spec)?.update();}
    function collect(){return $$('[data-expense]',tbody).filter(row=>$('input[type=checkbox]',row).checked).map(row=>({expense:Number(row.dataset.expense),shape:Number($('select',row).value),amount:amount(cents($('input[data-amount]',row).value))}));}
    function calculate(){let total=0n;const rows=$$('[data-expense]',tbody);rows.forEach(row=>{const included=$('input[type=checkbox]',row).checked;const money=cents($('[data-amount]',row).value);if(included&&money!==null)total+=money;row.classList.toggle('is-excluded',!included);$('select',row).disabled=!included;$('[data-amount]',row).disabled=!included;controls.get($('select',row))?.update();});rows.forEach(row=>{const m=cents($('[data-amount]',row).value)||0n;$('[data-share]',row).textContent=total&&$('input[type=checkbox]',row).checked?Number(m*10000n/total)/100+'%':'—';});$('[data-total]').textContent=formatter.format(Number(total)/100);const count=Number($('#id_beneficiaries').value)||0;$('#market-seat-cost').value=count?formatter.format(Number(total)/100/count):'0.00';hidden.value=JSON.stringify(collect());}
    function renderLines(saved,checkAll=false){opened?.close();$$('select',tbody).forEach(s=>controls.delete(s));tbody.replaceChildren();const p=catalog.programs.find(p=>String(p.id)===program.value);$('#market-category').value=catalog.funded_program_snapshot?.category||p?.category||'';$('#market-training-type').value=catalog.funded_program_snapshot?.type||p?.type||'';const ids=p?[...new Set([...p.expenses,...(String(p.id)===String(catalog.original_program)?catalog.old_expenses:[])])]:[];catalog.expenses.filter(e=>ids.includes(e.id)).forEach(expense=>{const old=saved.find(r=>r.expense===expense.id);const row=make('tr');row.dataset.expense=expense.id;const include=make('input');include.type='checkbox';include.checked=!!old||checkAll;include.setAttribute('aria-label','تضمين '+expense.name);const a=make('td');a.append(include);const name=make('th','',expense.name+(expense.is_active?'':' (محفوظ سابقًا)'));name.scope='row';const shapeCell=make('td'),select=make('select');select.id='market-shape-'+expense.id;select.dataset.label='شكل الرعاية لبند '+expense.name;select.setAttribute('aria-label',select.dataset.label);select.add(new Option('اختر شكل الرعاية',''));catalog.shapes.filter(s=>s.is_active||old?.shape===s.id).forEach(s=>select.add(new Option(s.name+(s.is_active?'':' (محفوظ سابقًا)'),s.id)));select.value=String(old?.shape||'');shapeCell.append(select);const moneyCell=make('td'),input=make('input');input.type='text';input.dataset.amount='';input.setAttribute('inputmode','decimal');input.setAttribute('dir','ltr');input.setAttribute('aria-label','المبلغ لبند '+expense.name);input.maxLength=40;input.value=old?.amount||'';moneyCell.append(input);const share=make('td');share.dataset.share='';row.append(a,name,shapeCell,moneyCell,share);tbody.append(row);enhance(select);include.addEventListener('change',()=>{if(!include.checked){ask('إزالة هذا البند من تكلفة الحاجة؟ سيُحفظ التغيير بعد حفظ البطاقة.',calculate,false,()=>{include.checked=true;calculate();});}else calculate();});select.addEventListener('change',calculate);input.addEventListener('input',calculate);});$('[data-expense-empty]').hidden=ids.length>0;calculate();}
    sector.addEventListener('change',()=>{const next=sector.value;if(next===previousSector)return;ask('تغيير القطاع سيعيد تحديد التخصص. راجع التخصص والبيانات المرتبطة قبل حفظ البطاقة.',()=>{spec.value='';previousSector=next;$('#id_dependencies_confirmed').value='true';filterSpecs();},false,()=>{sector.value=previousSector;controls.get(sector).update();});});
    program.addEventListener('change',()=>{const next=program.value;if(next===previousProgram)return;ask('تغيير البرنامج سيستبدل بنود الصرف الحالية. هل تريد المتابعة ومراجعة مبالغ وأشكال الرعاية مجددًا؟',()=>{previousProgram=next;$('#id_dependencies_confirmed').value='true';renderLines([],true);},false,()=>{program.value=previousProgram;controls.get(program).update();});});
    $('#id_beneficiaries').addEventListener('input',calculate);filterSpecs();renderLines(drafts,false);
    if(editor.dataset.financialLocked==='1'){
      ['#id_sector','#id_specialization','#id_regions','#id_program'].forEach(id=>{const select=$(id);select.dataset.marketLocked='1';controls.get(select)?.update();});
      $('#id_beneficiaries').readOnly=true;$('#id_requested_support').readOnly=true;
      $$('[data-expense]',tbody).forEach(row=>{$('input[type=checkbox]',row).disabled=true;$('[data-amount]',row).readOnly=true;const select=$('select',row);select.dataset.marketLocked='1';controls.get(select)?.update();});
    }
    syncEditor=()=>{calculate();const rows=collect(),error=$('[data-line-error]');if(!rows.length||rows.some(r=>!r.shape||cents(r.amount)===null||cents(r.amount)<=0n||cents(r.amount)>99999999999999n)){error.textContent='اختر بندًا واحدًا على الأقل، وحدد شكل الرعاية ومبلغًا موجبًا بمنزلتين عشريتين وبصيغة صحيحة لكل بند.';error.scrollIntoView({block:'center'});return false;}if(rows.reduce((sum,r)=>sum+cents(r.amount),0n)>99999999999999n){error.textContent='مجموع البنود يتجاوز الحد المالي المسموح.';return false;}error.textContent='';return true;};
  }

  const followup=$('[data-followup-form]'), followupDialog=$('#market-followup-dialog');let uploads=[];
  function fileList(){const root=$('[data-upload-files]');if(!root)return;root.replaceChildren();uploads.forEach((file,i)=>{const row=make('div'),label=make('span','',file.name),size=make('small','',formatter.format(file.size/1048576)+' MiB'),remove=make('button','','إزالة');remove.type='button';remove.setAttribute('aria-label','إزالة '+file.name);label.append(size);remove.addEventListener('click',()=>{uploads.splice(i,1);fileList();});row.append(label,remove);root.append(row);});}
  function syncFunding(validate=false){
    if(!followup)return true;
    const op=followup.dataset.operation, active=op==='approve'||op==='allocate';if(!active)return true;
    const total=cents(followup.dataset.totalCost)||0n, percent=cents($('#id_support_percent').value);
    let contribution=op==='allocate'?cents(followup.dataset.recordAmount):(percent!==null&&total?(total*percent+5000n)/10000n:null);
    $('#id_amount').value=amount(contribution);
    const level=contribution&&total?(contribution===total?'استراتيجي':contribution*100n>=total*80n?'ذهبي':contribution*100n>=total*60n?'فضي':'برونزي'):'—';$('[data-level-preview]').textContent=level;
    let sum=0n,valid=true;$$('[data-allocation-input]',followup).forEach(input=>{const value=input.disabled?0n:input.value.trim()?cents(input.value):0n;const remaining=cents(input.dataset.remaining)||0n;const error=$('#error-'+input.name,followup);if(value===null||value<0n||value>remaining){valid=false;if(validate&&error)error.textContent='أدخل مبلغًا صحيحًا لا يتجاوز المتبقي للبند.';}else{sum+=value;if(error)error.textContent='';}});
    $('[data-allocation-total]').textContent=formatter.format(Number(sum)/100);$('[data-allocation-status]').textContent=contribution!==null&&sum===contribution&&valid?'التوزيع يطابق مبلغ المساهمة.':'وزّع مبلغ المساهمة بالكامل على البنود.';
    const result=valid&&contribution!==null&&contribution>0n&&sum===contribution;
    if(validate&&!result)$('[data-followup-error]').textContent='راجع نسبة الدعم وتوزيع المساهمة؛ المجموع يجب أن يطابق مبلغ الدعم ولا يتجاوز المتبقي للبنود.';
    return result;
  }
  function configureFollowup(operation){
    followup.dataset.operation=operation;const approve=operation==='approve',allocate=operation==='allocate',funding=approve||allocate,reject=operation==='reject';
    $('[data-approval-fields]').hidden=!funding;$('[data-allocation-fields]').hidden=!funding;$('[data-rejection-fields]').hidden=!reject;$('[data-evidence-fields]').hidden=!approve;
    $('#id_amount').disabled=!funding;$('#id_amount').required=false;$('#id_amount').readOnly=true;
    $('#id_support_percent').disabled=!approve;$('#id_support_percent').required=approve;if(allocate){const total=cents(followup.dataset.totalCost),support=cents(followup.dataset.recordAmount);$('#id_support_percent').value=total&&support!==null?amount((support*10000n+total/2n)/total):'';}
    $('#id_rejection_reason').disabled=!reject;$('#id_rejection_reason').required=reject;$('#id_attachments').disabled=!approve;
    const allowed=(followup.dataset.allowedLines||'').split(',');$$('[data-allocation-input]',followup).forEach(input=>{input.disabled=!funding||cents(input.dataset.remaining)===0n||(approve&&!allowed.includes(input.dataset.lineId));});
    $('#followup-dialog-title').textContent=approve?'اعتماد مساهمة الجهة':allocate?'توزيع مساهمة سابقة على بنود الصرف':reject?'تسجيل رفض الجهة':'تسجيل نتيجة التواصل';
    $('[data-followup-submit]').textContent=approve?'حفظ واعتماد الدعم':allocate?'تأكيد توزيع الدعم السابق':reject?'حفظ الرفض':'حفظ المتابعة';syncFunding();
  }
  $$('[data-followup-open]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();followup.reset();uploads=[];fileList();$$('.field-error',followup).forEach(n=>n.textContent='');$('[data-upload-progress]').hidden=true;$('[name=snapshot]',followup).value=a.dataset.snapshot;$('[data-followup-name]').textContent=a.dataset.name;$('#id_notes').value=a.dataset.notes;followup.dataset.recordAmount=a.dataset.recordAmount||'';followup.dataset.allowedLines=a.dataset.allowedLines||'';configureFollowup(a.dataset.operation);show(followupDialog);}));
  if(followup){$('#id_support_percent').addEventListener('input',()=>syncFunding());$$('[data-allocation-input]',followup).forEach(input=>input.addEventListener('input',()=>syncFunding()));configureFollowup(followup.dataset.operation||'notes');$('#id_attachments').addEventListener('change',e=>{const error=$('[data-followup-error]');error.textContent='';for(const file of e.target.files){if(!/\.(pdf|png|jpe?g)$/i.test(file.name)||!file.size||file.size>Number(followup.dataset.limit)){error.textContent='نوع ملف غير مسموح أو حجم يتجاوز الحد. راجع التعليمات.';continue;}if(uploads.length>=Number(followup.dataset.maxFiles)){error.textContent='تجاوزت العدد المسموح للمرفقات.';break;}if(!uploads.some(f=>f.name===file.name&&f.size===file.size&&f.lastModified===file.lastModified))uploads.push(file);}e.target.value='';fileList();});followupDialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});}
  function sendFollowup(form){
    const body=new FormData(form);body.delete('attachments');uploads.forEach(f=>body.append('attachments',f));const area=$('[data-upload-progress]'),bar=$('progress',area),status=$('[data-upload-status]'),error=$('[data-followup-error]');const xhr=new XMLHttpRequest();busy=true;area.hidden=false;bar.value=0;status.textContent=uploads.length?'جار رفع مستندات الدعم…':'جار التحقق والحفظ…';error.textContent='';$$('button,input,textarea',form).forEach(n=>n.disabled=true);
    function unlock(){busy=false;$$('button,input,textarea',form).forEach(n=>n.disabled=false);configureFollowup(form.dataset.operation);}
    xhr.upload.addEventListener('progress',e=>{if(e.lengthComputable){bar.value=Math.floor(e.loaded/e.total*100);status.textContent=bar.value<100?'جار رفع المرفقات: '+bar.value+'%':'اكتمل الإرسال. جار التحقق من المحتوى وحفظ القرار…';}});
    xhr.addEventListener('load',()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{}if(xhr.status>=200&&xhr.status<300&&data?.redirect){location.assign(data.redirect);return;}unlock();status.textContent='لم يكتمل الحفظ. راجع الرسالة وأعد المحاولة.';error.textContent=data?.error||'تعذّر حفظ القرار. حدّث الصفحة للتحقق من النتيجة قبل إعادة المحاولة.';for(const [key,messages]of Object.entries(data?.fields||{})){const target=$('#error-'+key,form);if(target)target.textContent=messages.map(m=>m.message).join(' ');}error.focus();});
    xhr.addEventListener('error',()=>{unlock();status.textContent='انقطع الاتصال. تحقق من حالة البطاقة قبل إعادة الإرسال.';error.textContent='تعذّر الاتصال بالخادم؛ قد يكون القرار وصل. حدّث الصفحة للتحقق.';});
    xhr.addEventListener('timeout',()=>{unlock();error.textContent='انتهت مهلة الاتصال. حدّث الصفحة للتحقق من نتيجة الحفظ.';});
    xhr.open('POST',form.getAttribute('action')||location.href);xhr.setRequestHeader('X-Requested-With','XMLHttpRequest');xhr.timeout=600000;xhr.send(body);
  }
  $$('form[data-market-confirm]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();if(busy)return;if(form===editor&&!syncEditor())return;if(form===followup&&!syncFunding(true))return;if(form.matches('[data-candidates]')&&!$('input[name=organizations]:checked',form)){$('[data-candidate-error]').textContent='اختر جهة واحدة على الأقل للمتابعة.';return;}if(!form.reportValidity())return;ask(form.dataset.marketConfirm,()=>{if(form===followup){sendFollowup(form);return;}$$('button[type=submit]',form).forEach(b=>{b.disabled=true;b.textContent='جار الحفظ…';});HTMLFormElement.prototype.submit.call(form);},form.hasAttribute('data-danger')||form.dataset.operation==='reject');}));
})();
