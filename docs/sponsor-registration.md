# تسجيل الراعي الخارجي (US-15)

## المسارات
- **نموذج التسجيل العام (بدون تسجيل دخول):** `/partnerships/register/` (`partnerships:public_sponsor_register`)
- **صفحة التأكيد:** `/partnerships/register/submitted/` (`partnerships:public_sponsor_thanks`)
- **قائمة مراجعة الطلبات:** `/partnerships/requests/` (`partnerships:sponsor_requests`)
- **مراجعة واتخاذ القرار:** `/partnerships/requests/<id>/` (`partnerships:sponsor_request_review`)

## دورة حياة الحالة والصلاحيات
- تُحفظ جميع الطلبات الخارجية في جدول مستقل (`SponsorRegistrationRequest`) بحالة **`جديد` (`new`)** ولا تدخل سجل `Partnership` الرئيسي تلقائيًا.
- عند **الاعتماد** (يتطلب صلاحية `partnerships.create` ضمن النطاق المناطقي): يُنشأ سجل `Partnership` بالحالة الافتراضية المعتادة (`قدرة` / `CAPABILITY`) مع مناطقه الإدارية وعرض الرعاية الأولي، وتتحول حالة الطلب إلى **`معتمد` (`approved`)**.
- عند **الرفض** (يتطلب إدخال سبب الرفض): تتحول حالة الطلب إلى **`مرفوض` (`rejected`)** وتبقى مرفوضة نهائيًا دون إنشاء أي سجل في الشراكات.
