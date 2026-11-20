# إرسال البريد الفوري عبر RabbitMQ و Celery داخل Docker

## البنية التشغيلية
- **`rabbitmq` (`rabbitmq:3-alpine`):** وسيط رسائل داخلي على شبكة Docker فقط (غير مكشوف خارجيًا) مع وحدة تخزين دائمة `rabbitmq_data`.
- **`celery_worker`:** يعيد استخدام صورة `makken-prod-web` نفسها لتشغيل `celery -A makken worker --concurrency=2 --beat`.
- **الإرسال الفوري:** عند إنشاء أي سجل في `makken_mail.Delivery`، يُرسل رقم السجل فورًا إلى RabbitMQ عبر `transaction.on_commit` فيستلمه العامل خلال أقل من ثانية.
- **المعالجة الدورية الاحتياطية:** يعمل `celery --beat` كل 60 ثانية لتنفيذ `deliver_pending_mail` لإعادة المحاولات المؤجلة وتذكيرات انتهاء الشراكات.
