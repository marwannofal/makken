"""Tests for standalone تصنيف الاتفاقية lookup page, RBAC, and dependency protection."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess

from .models import AgreementClassification

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class AgreementClassificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser('cls_admin', 'cls_admin@example.com', 'StrongPass123!')
        self.reader = User.objects.create_user('cls_reader', 'cls_reader@example.com', 'StrongPass123!')
        acc, _ = UserAccess.objects.get_or_create(
            user=self.reader, defaults={'page_scope': 'all', 'region_scope': RegionScope.ALL}
        )
        acc.page_scope = 'all'
        acc.region_scope = RegionScope.ALL
        acc.save()
        PermissionOverride.objects.create(
            user=self.reader, module_id='agreement_classifications', operation='view', effect='grant'
        )
        self.url = reverse('agreement_clauses:classifications')

    def test_seeded_classifications_and_crud_flow(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        for label in (
            'الخدمات العامة والبحوث والدراسات',
            'التدريب والتأهيل والتطوير',
            'التوظيف',
            'الشراكة المجتمعية',
        ):
            self.assertContains(res, label)

        # Add new classification via modal
        add_get = self.client.get(self.url + '?edit=new')
        self.assertEqual(add_get.status_code, 200)
        add_post = self.client.post(self.url, {
            'operation': 'add',
            'snapshot': add_get.context['token'],
            'name': 'تصنيف اختباري جديد',
        })
        self.assertRedirects(add_post, self.url)
        created = AgreementClassification.objects.get(name='تصنيف اختباري جديد')

        # Edit classification
        edit_get = self.client.get(self.url + f'?edit={created.pk}')
        edit_post = self.client.post(self.url, {
            'operation': 'edit',
            'snapshot': edit_get.context['token'],
            'name': 'تصنيف اختباري محدث',
        })
        self.assertRedirects(edit_post, self.url)
        created.refresh_from_db()
        self.assertEqual(created.name, 'تصنيف اختباري محدث')

        # Toggle inactive and back active when unreferenced
        entries = self.client.get(self.url).context['row_items']
        entry = next(e for e in entries if e['item'].pk == created.pk)
        self.assertRedirects(
            self.client.post(self.url, {'operation': 'toggle', 'snapshot': entry['toggle_snapshot']}),
            self.url,
        )
        created.refresh_from_db()
        self.assertFalse(created.is_active)

        # Delete when unreferenced
        entries = self.client.get(self.url).context['row_items']
        entry = next(e for e in entries if e['item'].pk == created.pk)
        self.assertRedirects(
            self.client.post(self.url, {'operation': 'delete', 'snapshot': entry['delete_snapshot']}),
            self.url,
        )
        self.assertFalse(AgreementClassification.objects.filter(pk=created.pk).exists())

    def test_dependency_blocks_both_deactivate_and_delete_and_rbac_enforced(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        target = AgreementClassification.objects.first()
        entries = self.client.get(self.url).context['row_items']
        entry = next(e for e in entries if e['item'].pk == target.pk)

        with patch('core.dependencies.references_for', return_value=['سجلات اتفاقيات مرتبطة']):
            toggle_res = self.client.post(self.url, {'operation': 'toggle', 'snapshot': entry['toggle_snapshot']})
            self.assertEqual(toggle_res.status_code, 409)
            self.assertIn('dependency_block', toggle_res.context)
            target.refresh_from_db()
            self.assertTrue(target.is_active)

            del_res = self.client.post(self.url, {'operation': 'delete', 'snapshot': entry['delete_snapshot']})
            self.assertEqual(del_res.status_code, 409)
            self.assertIn('dependency_block', del_res.context)
            self.assertTrue(AgreementClassification.objects.filter(pk=target.pk).exists())

        # Read-only user can view (200) but cannot open add modal (403)
        self.client.force_login(self.reader, backend=AUTH_BACKEND)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.get(self.url + '?edit=new').status_code, 403)
