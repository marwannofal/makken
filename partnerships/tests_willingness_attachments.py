"""Private, validated multiple attachments are mandatory before willingness."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from PIL import Image
from pypdf import PdfWriter
from . import tests_development_transition as transitions
from .models import Partnership, WillingnessAttachment, PreliminaryAgreementType
from .willingness import MAX_FILE_SIZE, validate_attachment
from django import forms


def pdf(name='اتفاق مبدئي.pdf'):
    writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    stream=BytesIO();writer.write(stream)
    return SimpleUploadedFile(name,stream.getvalue(),content_type='application/pdf')


def image(kind='PNG',name='دليل.png'):
    stream=BytesIO();Image.new('RGB',(8,8),'#24B3AF').save(stream,format=kind)
    return SimpleUploadedFile(name,stream.getvalue(),content_type='image/png' if kind=='PNG' else 'image/jpeg')


class WillingnessAttachmentTests(TestCase):
    setUpTestData=classmethod(transitions.DevelopmentTransitionTests.setUpTestData.__func__)
    data=transitions.DevelopmentTransitionTests.data
    preview=transitions.DevelopmentTransitionTests.preview
    save=transitions.DevelopmentTransitionTests.save
    transition_preview=transitions.DevelopmentTransitionTests.transition_preview

    def setUp(self):
        self.private=TemporaryDirectory();self.addCleanup(self.private.cleanup)
        settings_override=override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=self.private.name)
        settings_override.enable();self.addCleanup(settings_override.disable)
        self.client.force_login(self.user)
        self.item,_=self.save();self.original=self.item.development_state_at
        self.url='/partnerships/?q='+self.item.name+'&capacity_min=10&capacity_max=200000'

    def post(self,files=None,agreement='official_letter',ajax=True,token=None):
        values={'action':'confirm','token':token or self.transition_preview(),'agreement_type':agreement}
        if files is not None:values['attachments']=files
        return self.client.post(self.url,values,**({'HTTP_X_REQUESTED_WITH':'XMLHttpRequest'} if ajax else {}))

    def assert_unchanged(self):
        self.item.refresh_from_db()
        self.assertEqual(self.item.development_state_id,'capability')
        self.assertEqual(self.item.development_state_at,self.original)
        self.assertEqual(self.item.preliminary_agreement_type,'')
        self.assertFalse(self.item.willingness_attachments.exists())
        self.assertFalse(self.item.development_history.filter(state_id='willingness').exists())
        self.assertFalse(any(Path(self.private.name).rglob('*.*')))

    def test_all_four_choices_and_required_form(self):
        self.assertEqual(list(PreliminaryAgreementType.labels),['خطاب رسمي','مذكرة موقعة','محضر اجتماع موقع','اتفاقية أو مذكرة تفاهم'])
        response=self.post()
        self.assertEqual(response.status_code,400)
        self.assertIn('attachments',response.json()['errors']);self.assert_unchanged()
        response=self.post([pdf()],agreement='')
        self.assertEqual(response.status_code,400);self.assertIn('agreement_type',response.json()['errors']);self.assert_unchanged()
        self.assertEqual(self.post([pdf()],agreement='forged-choice').status_code,400);self.assert_unchanged()

    def test_multi_upload_all_formats_and_detail_cards(self):
        for agreement in PreliminaryAgreementType.values:
            # Each choice is a real, valid enum value, independently checked by the form.
            from .willingness import WillingnessTransitionForm
            self.assertTrue(WillingnessTransitionForm({'agreement_type':agreement},{'attachments':[pdf()]}).is_valid())
        response=self.post([pdf(),image(),image('JPEG','صورة.jpg'),image('JPEG','صورة ثانية.jpeg')],agreement='agreement_or_mou')
        self.assertEqual(response.status_code,200,response.content)
        self.assertIn('redirect',response.json())
        self.item.refresh_from_db();self.assertEqual(self.item.development_state_id,'willingness')
        self.assertEqual(self.item.preliminary_agreement_type,'agreement_or_mou')
        self.assertEqual(self.item.willingness_attachments.count(),4)
        for attachment in self.item.willingness_attachments.all():
            self.assertTrue(Path(attachment.file.path).is_file())
            self.assertEqual(Path(attachment.file.path).stat().st_mode & 0o777,0o600)
            self.assertEqual(attachment.uploaded_by,self.user)
            self.assertTrue(attachment.file.name.startswith('willingness/'))
            with self.assertRaises(ValueError):_=attachment.file.url
        detail=self.client.get('/partnerships/',{'detail':self.item.pk})
        self.assertContains(detail,'المرفقات الداعمة للتحويل إلى رغبة')
        self.assertContains(detail,'اتفاقية أو مذكرة تفاهم')
        self.assertContains(detail,'willingness-attachment-card',count=4)
        self.assertContains(detail,'/download/',count=4)
        self.assertNotIn('private_uploads',detail.content.decode())

    def test_invalid_extension_empty_and_content_mismatch_are_rejected(self):
        for file in [SimpleUploadedFile('script.svg',b'<svg/>'),SimpleUploadedFile('empty.pdf',b''),SimpleUploadedFile('fake.pdf',b'<script>bad</script>'),SimpleUploadedFile('fake.png',b'not an image'),image('JPEG','wrong.png'),SimpleUploadedFile('broken.pdf',b'%PDF-1.7\nnot a real document')]:
            response=self.post([file]);self.assertEqual(response.status_code,400);self.assert_unchanged()

    def test_any_bad_file_rejects_entire_batch(self):
        self.assertEqual(self.post([pdf(),SimpleUploadedFile('bad.jpg',b'not a jpeg')]).status_code,400)
        self.assert_unchanged()

    def test_size_boundary_and_file_count(self):
        file=pdf();file.size=MAX_FILE_SIZE+1
        with self.assertRaises(forms.ValidationError):validate_attachment(file)
        file=pdf();file.size=MAX_FILE_SIZE
        self.assertIs(validate_attachment(file),file)
        self.assertEqual(self.post([pdf(f'file-{i}.pdf') for i in range(21)]).status_code,400)
        self.assert_unchanged()

    def test_download_is_authenticated_and_attachment_not_inline(self):
        self.assertEqual(self.post([pdf()]).status_code,200)
        attachment=self.item.willingness_attachments.get()
        url=f'/partnerships/{self.item.pk}/willingness/attachments/{attachment.pk}/download/'
        self.assertEqual(Client().get(url).status_code,302)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment;',response['Content-Disposition'])
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        self.assertEqual(self.client.get(url.replace(f'/{self.item.pk}/',f'/{self.item.pk+9999}/',1)).status_code,404)
        self.assertEqual(Client().get('/private_uploads/'+attachment.file.name).status_code,404)
        response=self.client.get(url)
        self.assertEqual(sum(map(len, response.streaming_content)), attachment.size)
        self.assertTrue(Partnership.objects.filter(pk=self.item.pk).exists())

    def test_existing_willingness_and_replay_do_not_add_files(self):
        token=self.transition_preview()
        self.assertEqual(self.post([pdf()],token=token).status_code,200)
        self.assertEqual(self.post([pdf('duplicate.pdf')],token=token).status_code,409)
        self.assertEqual(self.item.willingness_attachments.count(),1)
        self.assertEqual(len(list(Path(self.private.name).rglob('*.pdf'))),1)

    def test_database_failure_removes_written_files(self):
        with patch.object(WillingnessAttachment,'save',side_effect=IntegrityError('forced database failure')):
            self.assertEqual(self.post([pdf(),image()]).status_code,409)
        self.assert_unchanged()

    def test_second_file_failure_rolls_back_first_file_and_state(self):
        from .attachment_storage import PrivateAttachmentStorage
        original_save=PrivateAttachmentStorage.save
        count=0
        def fail_second(storage,*args,**kwargs):
            nonlocal count
            count+=1
            if count==2:raise OSError('forced storage failure')
            return original_save(storage,*args,**kwargs)
        with patch.object(PrivateAttachmentStorage,'save',new=fail_second):
            self.assertEqual(self.post([pdf(),image()]).status_code,503)
        self.assert_unchanged()

    def test_delete_cleans_private_files_after_commit(self):
        self.assertEqual(self.post([pdf()]).status_code,200)
        attachment=self.item.willingness_attachments.get();path=Path(attachment.file.path)
        with self.captureOnCommitCallbacks(execute=True):self.item.delete()
        self.assertFalse(path.exists())

    def test_non_ajax_validation_and_success(self):
        response=self.post([],ajax=False)
        self.assertEqual(response.status_code,400)
        self.assertContains(response,'أضف مرفقًا داعمًا واحدًا على الأقل.',status_code=400)
        self.assertContains(response,'data-willingness-form',status_code=400)
        self.assert_unchanged()
        self.assertEqual(self.post([pdf()],ajax=False).status_code,302)

    def test_untrusted_filename_escaped_in_details(self):
        self.assertEqual(self.post([pdf('<img onerror=alert(1)>.pdf')]).status_code,200)
        response=self.client.get('/partnerships/',{'detail':self.item.pk})
        self.assertNotIn('<img onerror=alert(1)>',response.content.decode())
        self.assertContains(response,'&lt;img onerror=alert(1)&gt;.pdf')
