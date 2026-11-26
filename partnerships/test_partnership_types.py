import json
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess
from agreement_clauses.models import AgreementClause, Responsibility
from care_states.models import DevelopmentState
from entities.models import Entity
from partnerships.models import Partnership, PartnershipType
from partnerships.partnership_types import _snapshot
from regions.models import Region

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


def _make_png(name='type-doc.png'):
    buf = BytesIO()
    Image.new('RGB', (16, 16), color=(36, 179, 175)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class PartnershipTypeAndSigningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('pt-admin', 'pt-admin@makken.test', 'AdminPass!9876')
        cls.reader = User.objects.create_user('pt-reader', 'pt-reader@makken.test', 'ReaderPass!9876')
        cls.none_user = User.objects.create_user('pt-none', 'pt-none@makken.test', 'NonePass!9876')
        UserAccess.objects.update_or_create(
            user=cls.reader, defaults={'page_scope': 'all', 'region_scope': RegionScope.ALL}
        )
        PermissionOverride.objects.create(
            user=cls.reader, module_id='partnership_types', operation='view', effect='grant'
        )
        cls.region = Region.objects.create(name='منطقة التوقيع للاختبار')
        cls.entity = Entity.objects.create(name='جهة اختبار أنواع الشراكة', entity_type='government')
        cls.clause = AgreementClause.objects.create(name='بند اختبار نوع الشراكة')
        cls.url = reverse('partnership_types')

    def test_seeded_partnership_types_and_rbac(self):
        names = set(PartnershipType.objects.values_list('name', flat=True))
        for expected in ('مذكرة تفاهم', 'تعاون', 'عقد خدمة', 'اجتماعية'):
            self.assertIn(expected, names)

        self.client.force_login(self.none_user, backend=AUTH_BACKEND)
        self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(self.reader, backend=AUTH_BACKEND)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'إضافة نوع شراكة')

    def test_crud_and_dependency_blocks_toggle_and_delete_no_cascade(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        add_page = self.client.get(f'{self.url}?edit=new')
        self.assertEqual(add_page.status_code, 200)
        res = self.client.post(self.url, {'operation': 'add', 'snapshot': add_page.context['token'], 'name': 'اتفاقية إطارية'})
        self.assertEqual(res.status_code, 302)
        pt = PartnershipType.objects.get(name='اتفاقية إطارية')

        # Link to a partnership
        p = Partnership.objects.create(
            name='شراكة مرتبطة بنوع',
            representative='سالم',
            phone_country='SA',
            phone='+966501112233',
            email='pt@makken.test',
            entity=self.entity,
            scope='local',
            partnership_type=pt,
            signing_region=self.region,
            signing_city='الرياض',
            created_by=self.admin,
        )

        # Toggle inactive blocked
        t_res = self.client.post(self.url, {'operation': 'toggle', 'snapshot': _snapshot(self.admin, 'toggle', pt)})
        self.assertEqual(t_res.status_code, 409)
        pt.refresh_from_db()
        self.assertTrue(pt.is_active)

        # Delete blocked
        d_res = self.client.post(self.url, {'operation': 'delete', 'snapshot': _snapshot(self.admin, 'delete', pt)})
        self.assertEqual(d_res.status_code, 409)
        self.assertTrue(PartnershipType.objects.filter(pk=pt.pk).exists())

        # ORM delete protected (no cascade)
        with self.assertRaises(ProtectedError):
            pt.delete()
        self.assertTrue(Partnership.objects.filter(pk=p.pk).exists())

    def test_willingness_transition_saves_db_partnership_type_signing_region_city_and_hides_exports(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        pt = PartnershipType.objects.get(name='مذكرة تفاهم')
        p = Partnership.objects.create(
            name='شراكة اختبار التوقيع',
            representative='عبدالله',
            phone_country='SA',
            phone='+966509998877',
            email='sign@makken.test',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
            created_by=self.admin,
        )
        p.administrative_regions.add(self.region)

        # Direct create page tables have data-no-export
        create_page = self.client.get(reverse('partnerships:create_willingness'))
        self.assertEqual(create_page.status_code, 200)
        self.assertContains(create_page, 'data-no-export')

        url = reverse('partnerships:capability_index')
        page = self.client.get(url)
        row = next(r for r in page.context['rows'] if r['item'].pk == p.pk)
        preview = self.client.post(url, {'action': 'preview', 'token': row['advance']})
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'data-no-export')

        ok = self.client.post(url, {
            'action': 'confirm',
            'token': preview.context['pending']['token'],
            'agreement_type': str(pt.pk),
            'attachments': _make_png(),
            'clauses_json': json.dumps([{'clause_id': self.clause.pk, 'responsibility': Responsibility.INSTITUTION}]),
            'work-title': 'متابعة توقيع الشراكة',
            'work-assignees': [str(self.reader.pk)],
            'work-manager': str(self.admin.pk),
            'details-signing_region': str(self.region.pk),
            'details-signing_city': 'جدة',
        })
        self.assertEqual(ok.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.partnership_type_id, pt.pk)
        self.assertEqual(p.signing_region_id, self.region.pk)
        self.assertEqual(p.signing_city, 'جدة')

    def test_classification_departments_and_hq_city_saved_and_protected(self):
        from accounts.models import Department
        from agreement_clauses.models import AgreementClassification
        from core.dependencies import DependencyBlocked, ensure_allowed

        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        cls_obj = AgreementClassification.objects.first()
        dept_objs = list(Department.objects.all()[:2])
        pt = PartnershipType.objects.get(name='مذكرة تفاهم')
        p = Partnership.objects.create(
            name='شراكة اختبار التصنيف والإدارات',
            representative='فيصل',
            phone_country='SA',
            phone='+966504445566',
            email='cls@makken.test',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
            created_by=self.admin,
        )
        p.administrative_regions.add(self.region)

        url = reverse('partnerships:capability_index')
        page = self.client.get(url)
        row = next(r for r in page.context['rows'] if r['item'].pk == p.pk)
        preview = self.client.post(url, {'action': 'preview', 'token': row['advance']})
        ok = self.client.post(url, {
            'action': 'confirm',
            'token': preview.context['pending']['token'],
            'agreement_type': str(pt.pk),
            'attachments': _make_png('cls.png'),
            'clauses_json': json.dumps([{'clause_id': self.clause.pk, 'responsibility': Responsibility.SHARED}]),
            'work-title': 'متابعة التصنيف والإدارات',
            'work-assignees': [str(self.reader.pk)],
            'work-manager': str(self.admin.pk),
            'details-agreement_classification': str(cls_obj.pk),
            'details-concerned_departments': [str(d.pk) for d in dept_objs],
            'details-headquarters_city': 'الخبر',
        })
        self.assertEqual(ok.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.agreement_classification_id, cls_obj.pk)
        self.assertEqual(p.headquarters_city, 'الخبر')
        self.assertEqual(set(p.concerned_departments.values_list('pk', flat=True)), {d.pk for d in dept_objs})

        # Dependency guard blocks deactivation & deletion of linked classification & departments
        with self.assertRaises(DependencyBlocked):
            ensure_allowed(cls_obj, 'toggle', active=False)
        with self.assertRaises(DependencyBlocked):
            ensure_allowed(cls_obj, 'delete')
        with self.assertRaises(DependencyBlocked):
            ensure_allowed(dept_objs[0], 'toggle', active=False)
        with self.assertRaises(DependencyBlocked):
            ensure_allowed(dept_objs[0], 'delete')
