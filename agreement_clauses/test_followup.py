from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from access_control.defaults import initialize
from access_control.models import PermissionOverride, UserAccess, UserActivity
from entities.models import Entity
from partnerships.attachment_storage import PrivateAttachmentStorage
from partnerships.models import Partnership
from regions.models import Region

from .models import Agreement, AgreementClause, AgreementDetails, AgreementEvidence, AgreementFollowupEntry, AgreementFollowupState, AgreementMember, ClauseAssignment

User = get_user_model()


class AgreementFollowupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('followup-admin', first_name='مسؤول المتابعة')
        cls.region = Region.objects.create(name='منطقة المتابعة')
        cls.other_region = Region.objects.create(name='منطقة ثانية للمتابعة')
        entity = Entity.objects.create(name='جهة اختبار المتابعة', entity_type='government')
        cls.partner = Partnership.objects.create(name='شراكة المتابعة', entity=entity, scope='local')
        cls.partner.administrative_regions.add(cls.region)
        cls.agreement = Agreement.objects.create(partnership=cls.partner, title='اتفاقية المتابعة', created_by=cls.admin)
        cls.other = Agreement.objects.create(partnership=cls.partner, title='اتفاقية أخرى')
        clause = AgreementClause.objects.create(name='تسليم التقرير')
        cls.row = ClauseAssignment.objects.create(agreement=cls.agreement, clause=clause, progress=25,
                                                   responsibility='shared', updated_by=cls.admin)
        cls.foreign_row = ClauseAssignment.objects.create(agreement=cls.other, clause=clause, responsibility='shared')
        cls.member = AgreementMember.objects.create(agreement=cls.agreement, side='institution', name='ضابط قديم',
                                                     organization='المؤسسة', role='contact')

    def setUp(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        self.url = reverse('partnerships:agreement', args=[self.partner.pk, self.agreement.pk])
        storage = TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        self.storage = Path(storage.name)
        settings = self.settings(MAKKEN_PRIVATE_UPLOAD_ROOT=storage.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def user(self, username, *ops, region=None):
        user = User.objects.create_user(username)
        rights = UserAccess.objects.create(user=user, page_scope='all', region_scope='selected')
        rights.allowed_regions.add(region or self.region)
        for op in ops:
            PermissionOverride.objects.create(user=user, module_id='partnerships', operation=op, effect='grant')
        return user

    @staticmethod
    def image(name='شاهد.png'):
        stream = BytesIO()
        Image.new('RGB', (12, 12), 'teal').save(stream, format='PNG')
        return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')

    def post_entry(self, **values):
        payload = {'operation': 'add_followup', 'snapshot': self.client.get(self.url).context['followup_token']}
        payload.update(values)
        return self.client.post(self.url, payload)

    def test_entry_and_multiple_files_write_once_and_are_visible_with_attribution(self):
        snapshot = self.client.get(self.url).context['followup_token']
        original = self.image()
        expected = original.read()
        original.seek(0)
        data = {'snapshot': snapshot, 'note': 'اعتماد التقرير<script>غير موثوق</script>', 'clause': self.row.pk}
        self.assertEqual(self.post_entry(**data, files=[original, self.image('وثيقة.png')]).status_code, 302)
        self.assertEqual(self.post_entry(**data, files=[self.image()]).status_code, 302)
        entry = AgreementFollowupEntry.objects.get()
        self.assertEqual(entry.clause_id, self.row.pk)
        self.assertEqual(entry.created_by, self.admin)
        self.assertEqual(entry.evidence.count(), 2)
        archive = self.client.get(self.url)
        self.assertContains(archive, 'بطاقة متابعة الاتفاقية')
        self.assertContains(archive, 'مسؤول المتابعة')
        self.assertContains(archive, 'اعتماد التقرير&lt;script&gt;')
        self.assertContains(archive, 'شاهد.png')
        self.assertEqual(archive.context['followup_updated_by'], self.admin)
        event = UserActivity.objects.get(description='إضافة تحديث متابعة الاتفاقية')
        self.assertEqual(event.after['attachment_count'], 2)
        self.assertNotIn('اعتماد التقرير', str(event.after))
        attachment = entry.evidence.first()
        uri = reverse('partnerships:agreement_evidence_download', args=[self.partner.pk, self.agreement.pk, attachment.pk])
        with self.captureOnCommitCallbacks(execute=True):
            result = self.client.get(uri)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result['Content-Type'], 'image/png')
        self.assertIn('attachment;', result['Content-Disposition'])
        self.assertIn('no-store', result['Cache-Control'])
        self.assertEqual(b''.join(result.streaming_content), expected)
        result.close()
        self.assertTrue(UserActivity.objects.filter(action='download', route='partnerships:agreement_evidence_download').exists())
        self.assertEqual(self.client.get(uri.replace(f'/agreements/{self.agreement.pk}/', f'/agreements/{self.other.pk}/')).status_code, 404)
        self.assertEqual(Client().get(uri).status_code, 302)

    def test_empty_foreign_clause_and_invalid_or_large_files_do_not_save(self):
        self.assertContains(self.post_entry(), 'أدخل ملاحظة', status_code=400)
        self.assertEqual(self.post_entry(note='اختبار', clause=self.foreign_row.pk).status_code, 400)
        self.assertContains(self.post_entry(files=[SimpleUploadedFile('fake.png', b'invalid')]), 'الملف تالف', status_code=400)
        with patch('agreement_clauses.followup.MAX_EVIDENCE_BYTES', 1):
            self.assertContains(self.post_entry(files=[self.image()]), 'الحد الأقصى لكل ملف', status_code=400)
        self.assertContains(self.post_entry(files=[self.image() for _ in range(6)]), 'خمسة ملفات', status_code=400)
        self.assertFalse(AgreementFollowupEntry.objects.exists())
        self.assertFalse(list(self.storage.glob('agreement-evidence/*')))

    def test_storage_failure_rolls_back_the_entry_and_cleans_written_files(self):
        save = PrivateAttachmentStorage.save

        def fail_second(storage, name, upload):
            if upload.name == 'fail.png':
                raise OSError('simulated storage failure')
            return save(storage, name, upload)

        with patch.object(PrivateAttachmentStorage, 'save', fail_second):
            self.assertEqual(self.post_entry(note='لا يحفظ', files=[self.image(), self.image('fail.png')]).status_code, 503)
        self.assertFalse(AgreementEvidence.objects.exists())
        self.assertFalse(AgreementFollowupEntry.objects.exists())
        self.assertFalse(AgreementFollowupState.objects.exists())
        self.assertFalse(list(self.storage.glob('agreement-evidence/*')))

    def test_editor_viewer_export_permissions_and_regions_are_independent(self):
        editor = self.user('card-editor', 'view', 'edit')
        self.client.force_login(editor)
        data = {'operation': 'add_followup', 'note': 'شاهد مسموح',
                'snapshot': self.client.get(self.url).context['followup_token'], 'files': [self.image()]}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        attachment = AgreementEvidence.objects.get()
        uri = reverse('partnerships:agreement_evidence_download', args=[self.partner.pk, self.agreement.pk, attachment.pk])
        self.assertEqual(self.client.get(uri).status_code, 403)
        viewer = self.user('card-reader', 'view', 'export')
        self.client.force_login(viewer)
        self.assertContains(self.client.get(self.url), 'شاهد مسموح')
        self.assertNotContains(self.client.get(self.url), 'حفظ تحديث المتابعة')
        self.assertEqual(self.client.post(self.url, data).status_code, 403)
        self.client.get(uri).close()
        self.client.force_login(self.user('card-outside', 'view', 'edit', 'export', region=self.other_region))
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(uri).status_code, 404)
        self.client.force_login(editor)
        self.partner.administrative_regions.add(self.other_region)
        self.assertContains(self.client.get(self.url), 'شاهد مسموح')
        self.assertNotContains(self.client.get(self.url, {'edit_team': '1'}), 'حفظ الفريقين')
        self.assertEqual(self.client.post(self.url, data).status_code, 403)

    def test_progress_and_team_updates_change_last_update_and_keep_the_shared_record(self):
        page = self.client.get(self.url)
        self.assertEqual(page.context['followup_updated_at'], self.row.updated_at)
        clause, _, signed = page.context['rows'][0]
        self.assertEqual(self.client.post(self.url, {'operation': 'update_clause', 'snapshot': signed,
            f'row-{clause.pk}-responsibility': 'shared', f'row-{clause.pk}-progress': '80'}).status_code, 302)
        current = self.client.get(self.url, {'edit_team': '1'})
        self.assertEqual(current.context['progress'], 80)
        first = current.context['followup_updated_at']
        data = {'operation': 'save_followup_teams', 'snapshot': current.context['teams_token'],
            'institution-TOTAL_FORMS': '1', 'institution-INITIAL_FORMS': '1',
            'institution-0-id': self.member.pk, 'institution-0-name': 'ضابط محدث',
            'institution-0-organization': 'المؤسسة', 'institution-0-role': 'contact',
            'partner-TOTAL_FORMS': '1', 'partner-INITIAL_FORMS': '0', 'partner-0-name': 'ضابط الجهة',
            'partner-0-role': 'contact', 'partner-0-organization': 'الشريك'}
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        profile_url = reverse('partnerships:agreement_details', args=[self.partner.pk, self.agreement.pk])
        profile = self.client.get(profile_url)
        self.assertContains(profile, 'ضابط محدث')
        self.assertContains(profile, 'ضابط الجهة')
        self.assertEqual(AgreementDetails.objects.get().updated_by, self.admin)
        self.assertGreater(self.client.get(self.url).context['followup_updated_at'], first)

    def test_clause_removal_preserves_history_and_updates_card(self):
        self.assertEqual(self.post_entry(note='تحديث سابق', clause=self.row.pk).status_code, 302)
        before = self.client.get(self.url)
        _, _, signed = before.context['rows'][0]
        self.assertEqual(self.client.post(self.url, {'operation': 'remove_clause', 'snapshot': signed}).status_code, 302)
        self.assertIsNone(AgreementFollowupEntry.objects.get().clause_id)
        page = self.client.get(self.url)
        self.assertContains(page, 'تسليم التقرير')
        self.assertGreater(page.context['followup_updated_at'], before.context['followup_updated_at'])
