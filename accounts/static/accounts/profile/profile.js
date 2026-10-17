(() => {
  'use strict';
  document.querySelectorAll('[data-password-toggle]').forEach(button=>{
    button.addEventListener('click',()=>{
      const input=document.getElementById(button.getAttribute('aria-controls'));
      const shown=input.type==='password';input.type=shown?'text':'password';
      button.setAttribute('aria-pressed',String(shown));
      const label=document.querySelector(`label[for="${input.id}"]`).textContent.replace('*','').trim();
      button.setAttribute('aria-label',(shown?'إخفاء ':'إظهار ')+label);
      button.querySelector('.profile-eye').hidden=shown;button.querySelector('.profile-eye-off').hidden=!shown;
    });
  });
  const detailForm=document.querySelector('[data-form-kind=details]');
  const email=detailForm.querySelector('[name=email]'),emailConfirm=detailForm.querySelector('[name=email_confirm]');
  function checkEmail(){
    const changed=email.value.trim().toLowerCase()!==detailForm.dataset.currentEmail.trim().toLowerCase();
    emailConfirm.required=changed;
    emailConfirm.setCustomValidity(emailConfirm.value&&emailConfirm.value.trim().toLowerCase()!==email.value.trim().toLowerCase()?'أعد كتابة البريد الإلكتروني نفسه لتأكيده.':'');
  }
  email.addEventListener('input',checkEmail);emailConfirm.addEventListener('input',checkEmail);checkEmail();
  const passwordForm=document.querySelector('[data-form-kind=password]');
  const password=passwordForm.querySelector('[name=new_password1]'),confirmation=passwordForm.querySelector('[name=new_password2]');
  const minimum=Number(passwordForm.dataset.passwordMinimum);
  function checkPassword(){
    const value=password.value;
    const rules={length:value.length>=minimum&&value.length<=128,upper:/[A-Z]/.test(value),lower:/[a-z]/.test(value),number:/[0-9]/.test(value),symbol:/[^\p{L}\p{N}\p{M}\p{C}\s]/u.test(value),spaces:value.length>0&&!/[\s\p{C}]/u.test(value)};
    document.querySelectorAll('[data-password-rule]').forEach(item=>item.classList.toggle('is-met',rules[item.dataset.passwordRule]));
    const met=Object.values(rules).filter(Boolean).length;
    document.querySelector('[data-password-live]').textContent=value?(met===6?'الشروط الأساسية مستوفاة؛ سيتم التحقق النهائي عند الحفظ.':`تحققت ${met} من 6 شروط أساسية.`):'';
    password.setCustomValidity(value&&met!==6?'أكمل شروط كلمة المرور الموضحة أدناه.':'');
    confirmation.setCustomValidity(confirmation.value&&confirmation.value!==value?'كلمتا المرور غير متطابقتين.':'');
  }
  password.addEventListener('input',checkPassword);confirmation.addEventListener('input',checkPassword);checkPassword();
  const select=detailForm.querySelector('[name=phone_country]');
  if(select && window.Intl?.DisplayNames){
    const catalog=JSON.parse(document.getElementById('profile-country-catalog').textContent);
    const names=new Intl.DisplayNames(['ar'],{type:'region'});
    const wrapper=select.parentElement;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='profile-country-trigger';
    trigger.setAttribute('aria-label','رمز الدولة');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-controls','profile-country-panel');
    const panel=document.createElement('div');panel.className='profile-country-panel';panel.id='profile-country-panel';panel.hidden=true;
    const search=document.createElement('input');search.type='search';search.placeholder='ابحث عن الدولة أو الرمز…';search.setAttribute('aria-label','البحث عن الدولة');search.autocomplete='off';
    const options=document.createElement('div');options.className='profile-country-options';options.setAttribute('role','listbox');options.setAttribute('aria-label','الدول ورموز الاتصال');
    const empty=document.createElement('p');empty.className='profile-country-empty';empty.textContent='لا توجد نتائج مطابقة.';empty.hidden=true;
    catalog.forEach(country=>{
      const option=document.createElement('button');option.type='button';option.className='profile-country-option';option.dataset.country=country.id;option.setAttribute('role','option');
      const flag=[...country.id].map(c=>String.fromCodePoint(127397+c.charCodeAt())).join('');
      option.textContent=`${flag} ${names.of(country.id)} (${country.dial})`;
      option.addEventListener('click',()=>{select.value=country.id;select.dispatchEvent(new Event('change',{bubbles:true}));refresh();close();trigger.focus();});options.append(option);
    });
    panel.append(search,options,empty);wrapper.append(trigger,panel);
    select.classList.add('profile-country-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    function close(){panel.hidden=true;trigger.setAttribute('aria-expanded','false');}
    function filter(){const term=search.value.trim().normalize('NFKC').toLowerCase();let count=0;options.querySelectorAll('button').forEach(option=>{option.hidden=!option.textContent.normalize('NFKC').toLowerCase().includes(term);if(!option.hidden)count++;});empty.hidden=count!==0;}
    function refresh(){const current=catalog.find(country=>country.id===select.value);trigger.textContent=current?`${current.id} ${current.dial}`:'اختر الدولة';options.querySelectorAll('button').forEach(option=>option.setAttribute('aria-selected',String(option.dataset.country===select.value)));trigger.setAttribute('aria-invalid',select.getAttribute('aria-invalid')||'false');}
    trigger.addEventListener('click',()=>{if(!panel.hidden){close();return;}panel.hidden=false;trigger.setAttribute('aria-expanded','true');search.value='';filter();search.focus();});
    trigger.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();if(panel.hidden)trigger.click();else search.focus();}});
    wrapper.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&!panel.hidden){event.preventDefault();event.stopPropagation();close();trigger.focus();}
      if(!panel.hidden&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        if(event.target===search&&['Home','End'].includes(event.key))return;
        const shown=[...options.querySelectorAll('button')].filter(button=>!button.hidden);if(!shown.length)return;
        event.preventDefault();let index=shown.indexOf(document.activeElement);
        index=event.key==='Home'?0:event.key==='End'?shown.length-1:(index+(event.key==='ArrowUp'?-1:1)+shown.length)%shown.length;shown[index].focus();
      }
    });
    search.addEventListener('input',filter);select.addEventListener('change',refresh);
    select.addEventListener('invalid',event=>{event.preventDefault();trigger.focus();});
    document.addEventListener('click',event=>{if(!wrapper.contains(event.target))close();});
    document.addEventListener('focusin',event=>{if(!wrapper.contains(event.target))close();});
    detailForm.addEventListener('reset',()=>requestAnimationFrame(()=>{refresh();close();checkEmail();}));refresh();
  }
  const confirm=document.getElementById('profile-confirmation');let pending=null;
  document.querySelectorAll('[data-profile-form]').forEach(form=>form.addEventListener('submit',event=>{
    if(form.dataset.confirmed==='true'){const button=form.querySelector('button[type=submit]');button.disabled=true;button.textContent='جارٍ الحفظ…';return;}
    if(typeof confirm.showModal!=='function')return;
    event.preventDefault();if(!form.reportValidity())return;
    pending=form;
    document.getElementById('profile-confirm-title').textContent=form.dataset.formKind==='password'?'تأكيد تغيير كلمة المرور':'تأكيد تحديث البيانات الشخصية';
    confirm.querySelector('[data-profile-confirm-description]').textContent=form.dataset.formKind==='password'?'هل تريد حفظ كلمة المرور الجديدة؟ ستبقى هذه الجلسة نشطة ويُطلب تسجيل الدخول مجددًا من الجلسات الأخرى.':'هل تريد حفظ بياناتك الشخصية ووسائل التواصل الجديدة؟';
    confirm.showModal();
  }));
  document.querySelector('[data-profile-confirm]').addEventListener('click',()=>{
    const form=pending;if(!form)return;pending=null;confirm.close();form.dataset.confirmed='true';form.requestSubmit();
  });
  confirm.addEventListener('close',()=>{pending=null;});
  document.querySelectorAll('[data-profile-dialog-close]').forEach(button=>button.addEventListener('click',()=>{const dialog=button.closest('dialog');dialog.close();if(dialog.id==='profile-success')document.getElementById('main-content').focus({preventScroll:true});}));
  const success=document.querySelector('[data-profile-success]');
  if(success&&typeof success.showModal==='function'){success.removeAttribute('open');success.showModal();}
  const errors=document.querySelector('[data-profile-errors]');if(errors&&!success)errors.focus();
})();
