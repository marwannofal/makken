import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from access_control.defaults import initialize
from agreement_clauses.models import AgreementClause, ClauseAssignment, Responsibility
from care_states.models import DevelopmentState
from entities.models import Entity
from makken_mail.models import WorkAssignment
from partnerships.models import Partnership, PreliminaryAgreementType
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


def _make_png(name='doc.png'):
    buf = BytesIO()
    Image.new('RGB', (16, 16), color=(36, 179, 175)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class WillingnessUnifiedWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('wf-admin', 'wf-admin@makken.test', 'AdminPass!9876')
        cls.emp = User.objects.create_user('wf-emp', 'wf-emp@makken.test', 'EmpPass!9876', first_name='أحمد', last_name='العتيبي')
        cls.mgr = User.objects.create_user('wf-mgr', 'wf-mgr@makken.test', 'MgrPass!9876', first_name='سارة', last_name='الحربي')
        cls.region = Region.objects.create(name='منطقة الرياض للاختبار الموحد')
        cls.entity = Entity.objects.create(name='جهة اختبار الرغبة الموحد', entity_type='government')
        cls.sector = Sector.objects.create(name='قطاع التقنية الموحد')
        cls.spec = Specialization.objects.create(name='تخصص البرمجة الموحد', sector=cls.sector)
        cls.shape = SponsorshipShape.objects.create(name='رعاية تدريب موحدة', description='وصف')
        cls.clause_1 = AgreementClause.objects.create(name='بند تنفيذ البرنامج التدريبي')
        cls.clause_2 = AgreementClause.objects.create(name='بند تقديم التقارير الدورية')

    def setUp(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

    def _create_capability(self, name='شراكة قدرة للتحويل'):
        p = Partnership.objects.create(
            name=name,
            representative='خالد محمد',
            phone_country='SA',
            phone='+966501234567',
            email='cap@makken.test',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
            created_by=self.admin,
        )
        p.administrative_regions.add(self.region)
        return p

    def test_capability_to_willingness_requires_documents_clauses_and_work_atomically(self):
        p = self._create_capability()
        url = reverse('partnerships:willingness_index')
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)

        row = next(r for r in page.context['rows'] if r['item'].pk == p.pk)
        preview = self.client.post(url, {'action': 'preview', 'token': row['advance']})
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'willingness-big-dialog')
        self.assertContains(preview, 'بنود الاتفاقية')
        self.assertContains(preview, 'إسناد عمل')
        self.assertNotContains(preview, 'target_model')
        confirm_token = preview.context['pending']['token']

        # Missing clauses and work -> 400, remains CAPABILITY, no side effects
        bad = self.client.post(url, {
            'action': 'confirm',
            'token': confirm_token,
            'agreement_type': PreliminaryAgreementType.MOU,
            'attachments': _make_png(),
            'clauses_json': '[]',
        })
        self.assertEqual(bad.status_code, 400)
        p.refresh_from_db()
        self.assertEqual(p.development_state_id, DevelopmentState.CAPABILITY)
        self.assertEqual(ClauseAssignment.objects.filter(partnership=p).count(), 0)
        self.assertEqual(WorkAssignment.objects.filter(target_model='partnerships.partnership', target_key=p.pk).count(), 0)

        # Complete submission -> 302, transitions to WILLINGNESS + saves clauses (progress=0) + creates linked WorkAssignment
        clauses_payload = json.dumps([
            {'clause_id': self.clause_1.pk, 'responsibility': Responsibility.PARTNER, 'progress': 75},
            {'clause_id': self.clause_2.pk, 'responsibility': Responsibility.INSTITUTION},
        ])
        ok = self.client.post(url, {
            'action': 'confirm',
            'token': confirm_token,
            'agreement_type': PreliminaryAgreementType.MOU,
            'attachments': _make_png(),
            'clauses_json': clauses_payload,
            'work-title': 'متابعة تفعيل الشراكة',
            'work-instructions': 'التواصل مع ممثل الجهة',
            'work-assignees': [str(self.emp.pk)],
            'work-manager': str(self.mgr.pk),
        })
        self.assertEqual(ok.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.development_state_id, DevelopmentState.WILLINGNESS)

        assigned = list(ClauseAssignment.objects.filter(partnership=p, agreement__isnull=True).order_by('clause_id'))
        self.assertEqual(len(assigned), 2)
        # Progress must be forced to 0 on initial transition even if client sent 75
        self.assertEqual([c.progress for c in assigned], [0, 0])
        self.assertEqual(assigned[0].responsibility, Responsibility.PARTNER)
        self.assertEqual(assigned[1].responsibility, Responsibility.INSTITUTION)

        work = WorkAssignment.objects.get(target_model='partnerships.partnership', target_key=p.pk)
        self.assertEqual(work.title, 'متابعة تفعيل الشراكة')
        self.assertEqual(work.manager_id, self.mgr.pk)
        self.assertEqual(list(work.assignees.values_list('pk', flat=True)), [self.emp.pk])

    def test_direct_willingness_creation_inline_sections_and_edit_progress(self):
        create_url = reverse('partnerships:create_willingness')
        page = self.client.get(create_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'نوع الاتفاق المبدئي والمرفقات الداعمة')
        self.assertContains(page, 'بنود الاتفاقية')
        self.assertContains(page, 'إسناد عمل')
        snapshot = page.context['snapshot']

        offerings = json.dumps([{
            'sector': self.sector.pk,
            'specializations': [self.spec.pk],
            'shape': self.shape.pk,
            'is_active': True,
        }])
        clauses_payload = json.dumps([
            {'clause_id': self.clause_1.pk, 'responsibility': Responsibility.SHARED},
        ])
        res = self.client.post(create_url, {
            'action': 'create_willingness',
            'snapshot': snapshot,
            'name': 'شراكة رغبة مباشرة جديدة',
            'representative': 'سلمان الدوسري',
            'phone_country': 'SA',
            'phone': '0501234567',
            'email': 'direct@makken.test',
            'financial_capacity': '50000',
            'entity_type': 'government',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(self.region.pk)],
            'is_active': '1',
            'offerings': offerings,
            'agreement_type': PreliminaryAgreementType.COOPERATION,
            'attachments': _make_png('direct.png'),
            'clauses_json': clauses_payload,
            'work-title': 'إعداد خطة التنفيذ',
            'work-assignees': [str(self.emp.pk)],
            'work-manager': str(self.mgr.pk),
        })
        self.assertEqual(res.status_code, 302)
        p = Partnership.objects.get(name='شراكة رغبة مباشرة جديدة')
        self.assertEqual(p.development_state_id, DevelopmentState.WILLINGNESS)
        ca = ClauseAssignment.objects.get(partnership=p, agreement__isnull=True)
        self.assertEqual(ca.progress, 0)
        self.assertEqual(ca.responsibility, Responsibility.SHARED)
        self.assertTrue(WorkAssignment.objects.filter(target_model='partnerships.partnership', target_key=p.pk).exists())

        # Now edit the partnership and update clause progress to 80%
        edit_url = reverse('partnerships:edit', kwargs={'pk': p.pk})
        edit_page = self.client.get(edit_url)
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, 'بنود الاتفاقية ونسب الإنجاز')
        self.assertNotContains(edit_page, 'عرض الاتفاقيات والبنود')

        updated_clauses = json.dumps([
            {'clause_id': self.clause_1.pk, 'responsibility': Responsibility.INSTITUTION, 'progress': 80},
        ])
        preview = self.client.post(edit_url, {
            'action': 'preview',
            'snapshot': edit_page.context['snapshot'],
            'name': p.name,
            'representative': p.representative,
            'phone_country': p.phone_country,
            'phone': p.phone,
            'email': p.email,
            'financial_capacity': '50000',
            'entity_type': 'government',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(self.region.pk)],
            'is_active': '1',
            'offerings': offerings,
            'clauses_json': updated_clauses,
        })
        self.assertEqual(preview.status_code, 200)
        confirm = self.client.post(edit_url, {
            'action': 'confirm',
            'token': preview.context['pending']['token'],
        })
        self.assertEqual(confirm.status_code, 302)
        ca.refresh_from_db()
        self.assertEqual(ca.progress, 80)
        self.assertEqual(ca.responsibility, Responsibility.INSTITUTION)

    def test_old_agreement_creation_ui_is_removed(self):
        p = self._create_capability('شراكة اختبار إزالة الاتفاقيات')
        clauses_url = reverse('partnerships:clauses', kwargs={'pk': p.pk})
        res = self.client.get(clauses_url)
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'operation" value="create_agreement"')
        self.assertNotContains(res, 'إضافة اتفاقية')

    def test_willingness_saves_us16_freetext_expiry_teams_and_accordions(self):
        from datetime import date
        from partnerships.models import PartnershipTeamMember, RenewalRule, TeamMemberRole, TeamSide

        p = self._create_capability('شراكة اختبار الحقول النصية والفرق')
        url = reverse('partnerships:willingness_index')
        page = self.client.get(url)
        row = next(r for r in page.context['rows'] if r['item'].pk == p.pk)
        preview = self.client.post(url, {'action': 'preview', 'token': row['advance']})
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'class="mk-accordion"')
        self.assertContains(preview, 'class="mk-acc-arrow"')
        self.assertNotContains(preview, 'data-dismiss-dialog autofocus>إلغاء')

        teams_payload = json.dumps([
            {'side': TeamSide.INSTITUTION, 'name': 'فهد الشمري', 'phone': '+966501112222', 'email': 'fahad@tvtc.gov.sa', 'organization': 'الإدارة العامة للتشاركية', 'role': TeamMemberRole.CONTACT},
            {'side': TeamSide.PARTNER, 'name': 'نورة القحطاني', 'phone': '+966503334444', 'email': 'noura@partner.sa', 'organization': 'إدارة المسؤولية المجتمعية', 'role': TeamMemberRole.LEAD},
        ])
        res = self.client.post(url, {
            'action': 'confirm',
            'token': preview.context['pending']['token'],
            'agreement_type': PreliminaryAgreementType.MOU,
            'attachments': _make_png('us16.png'),
            'clauses_json': json.dumps([{'clause_id': self.clause_1.pk, 'responsibility': Responsibility.SHARED}]),
            'work-title': 'متابعة اتفاقية الحقول الكاملة',
            'work-assignees': [str(self.emp.pk)],
            'work-manager': str(self.mgr.pk),
            'details-institution_signatory': 'د. أحمد الفهد',
            'details-institution_signatory_title': 'نائب المحافظ',
            'details-partner_signatory': 'م. عمر السبيعي',
            'details-partner_signatory_title': 'الرئيس التنفيذي',
            'details-signed_on': '2026-01-15',
            'details-duration_months': '24',
            'details-renewal_rule': RenewalRule.AUTOMATIC,
            'details-objective': 'تأهيل وتوظيف المتدربين',
            'details-announcement': 'توقيع شراكة استراتيجية',
            'details-audience': 'خريجو الكليات التقنية',
            'details-expected_results': 'توظيف 200 متدرب',
            'teams_json': teams_payload,
        })
        self.assertEqual(res.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.development_state_id, DevelopmentState.WILLINGNESS)
        self.assertEqual(p.agreement_number, p.format_agreement_number())
        list_page = self.client.get(url)
        self.assertContains(list_page, 'رقم الاتفاقية')
        self.assertContains(list_page, p.agreement_number)
        self.assertEqual(p.institution_signatory, 'د. أحمد الفهد')
        self.assertEqual(p.signed_on, date(2026, 1, 15))
        self.assertEqual(p.duration_months, 24)
        self.assertEqual(p.calculated_expiry, date(2028, 1, 15))
        self.assertEqual(p.renewal_rule, RenewalRule.AUTOMATIC)
        self.assertEqual(p.objective, 'تأهيل وتوظيف المتدربين')
        self.assertEqual(PartnershipTeamMember.objects.filter(partnership=p).count(), 2)
