from decimal import Decimal
import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import partnerships.models


class Migration(migrations.Migration):

    dependencies = [
        ('entities', '0002_named_name_key_unique'),
        ('partnerships', '0008_partnership_term_dates'),
        ('regions', '0002_named_name_key_unique'),
        ('sectors', '0002_named_name_key_unique'),
        ('sponsorship_shapes', '0002_named_name_key_unique'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SponsorRegistrationRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reference_code', models.CharField(editable=False, max_length=24, unique=True, verbose_name='رقم الطلب')),
                ('name', models.CharField(max_length=200, validators=[partnerships.models.validate_name], verbose_name='اسم الجهة')),
                ('name_key', models.CharField(db_index=True, editable=False, max_length=600)),
                ('representative', models.CharField(max_length=200, validators=[partnerships.models.validate_name], verbose_name='اسم الممثل عن الجهة')),
                ('phone_country', models.CharField(default='SA', max_length=2)),
                ('phone', models.CharField(max_length=16, verbose_name='هاتف التواصل')),
                ('email', models.EmailField(max_length=254, verbose_name='البريد الإلكتروني')),
                ('scope', models.CharField(choices=[('local', 'محلي'), ('global', 'عالمي')], default='local', max_length=8, verbose_name='النطاق')),
                ('financial_capacity', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='القدرة المالية')),
                ('notes', models.TextField(blank=True, max_length=2000, verbose_name='نبذة وملاحظات إضافية')),
                ('status', models.CharField(choices=[('new', 'جديد'), ('approved', 'معتمد'), ('rejected', 'مرفوض')], db_index=True, default='new', max_length=12, verbose_name='حالة الطلب')),
                ('rejection_reason', models.TextField(blank=True, max_length=1000, verbose_name='سبب الرفض')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='تاريخ المراجعة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('administrative_regions', models.ManyToManyField(blank=True, related_name='sponsor_requests', to='regions.region', verbose_name='المناطق الإدارية للجهة')),
                ('created_partnership', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_registration_request', to='partnerships.partnership', verbose_name='الشراكة المنشأة')),
                ('entity', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='sponsor_requests', to='entities.entity', verbose_name='الكيان')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_sponsor_requests', to=settings.AUTH_USER_MODEL, verbose_name='تمت المراجعة بواسطة')),
                ('sector', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sponsor_requests', to='sectors.sector', verbose_name='القطاع')),
                ('sponsorship_shape', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sponsor_requests', to='sponsorship_shapes.sponsorshipshape', verbose_name='شكل الرعاية')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'default_permissions': (),
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('status__in', ['new', 'approved', 'rejected'])), name='sponsor_request_status_enum'),
                    models.CheckConstraint(condition=models.Q(('scope__in', ['local', 'global'])), name='sponsor_request_scope_enum'),
                    models.CheckConstraint(condition=models.Q(('financial_capacity__isnull', True), ('financial_capacity__gte', 0), _connector='OR'), name='sponsor_request_financial_nonnegative'),
                ],
            },
        ),
    ]
