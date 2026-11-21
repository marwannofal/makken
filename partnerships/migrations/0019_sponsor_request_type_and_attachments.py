from django.db import migrations, models
import django.db.models.deletion
import partnerships.attachment_storage
import partnerships.models


class Migration(migrations.Migration):

    dependencies = [
        ('partnerships', '0018_sponsor_request_offerings'),
    ]

    operations = [
        migrations.AddField(
            model_name='sponsorregistrationrequest',
            name='partnership_type',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='sponsor_requests',
                to='partnerships.partnershiptype',
                verbose_name='نوع الشراكة',
            ),
        ),
        migrations.CreateModel(
            name='SponsorRequestAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(max_length=255, storage=partnerships.attachment_storage.willingness_storage, upload_to=partnerships.models.sponsor_attachment_path)),
                ('original_name', models.CharField(max_length=255)),
                ('size', models.PositiveBigIntegerField()),
                ('content_type', models.CharField(max_length=40)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('sponsor_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='partnerships.sponsorregistrationrequest')),
            ],
            options={
                'ordering': ['id'],
                'default_permissions': (),
            },
        ),
    ]
