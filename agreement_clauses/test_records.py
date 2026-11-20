from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, UserAccess, UserActivity
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .models import Agreement, AgreementClause, AgreementDetails, AgreementMember, AgreementOption, AgreementRenewal, ClauseAssignment

User = get_user_model()


class AgreementRecordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('agreement-record-admin')
        cls.region = Region.objects.create(name='منطقة سجل الاتفاقية')
        cls.other_region = Region.objects.create(name='منطقة سجل أخرى')
        cls.entity = Entity.objects.create(name='كيان سجل الاتفاقية', entity_type='government')
        cls.partner = Partnership.objects.create(
            name='شراكة السجل الداخلي', representative='ممثل', phone='+966501234567', email='partner@example.org',
            entity=cls.entity, scope='local', starts_on=date(2025, 5, 1), ends_on=date(2029, 5, 1),
        )
        cls.partner.administrative_regions.add(cls.region)
        cls.agreement = Agreement.objects.create(partnership=cls.partner, title='اتفاقية السجل الداخلي')
        clause = AgreementClause.objects.create(name='إنجاز محفوظ')
        ClauseAssignment.objects.create(agreement=cls.agreement, clause=clause, responsibility='shared', progress=65)
        cls.department = AgreementOption.objects.get(kind='department', name='الكليات')
        cls.classification = AgreementOption.objects.get(kind='classification', name='التوظيف')

    def setUp(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        self.url = reverse('partnerships:agreement_details', args=[self.partner.pk, self.agreement.pk])

    def limited(self, username, region, *ops, module='partnerships'):
        user = User.objects.create_user(username)
        access = UserAccess.objects.create(user=user, page_scope='all', region_scope='selected')
        access.allowed_regions.add(region)
        for operation in ops:
            PermissionOverride.objects.create(user=user, module_id=module, operation=operation, effect='grant')
        return user

    def payload(self, **extra):
        data = {
            'operation': 'save_details', 'snapshot': self.client.get(self.url, {'edit': '1'}).context['save_token'],
            'signed_on': '2028-01-31', 'duration_months': '1', 'renewal_rule': 'prior_approval',
            'classification': self.classification.pk, 'departments': [self.department.pk],
            'institution_signatory': 'موقّع المؤسسة', 'institution_signatory_title': 'مدير المؤسسة',
            'partner_signatory': 'موقّع الجهة', 'partner_signatory_title': 'مدير الجهة',
            'partner_phone': '+966501234567', 'partner_email': 'contact@example.org',
            'objective': 'تبادل الخبرات', 'responsible_employee': self.admin.pk,
            'institution-TOTAL_FORMS': '1', 'institution-INITIAL_FORMS': '0',
            'institution-0-name': 'ضابط المؤسسة', 'institution-0-organization': 'المؤسسة',
            'institution-0-role': 'contact', 'institution-0-email': 'officer@example.org',
            'partner-TOTAL_FORMS': '1', 'partner-INITIAL_FORMS': '0',
            'partner-0-name': 'ممثل الجهة', 'partner-0-organization': 'الجهة',
            'partner-0-role': 'representative', 'partner-0-phone': '٠٥٠١٢٣٤٥٦٧',
        }
        data.update(extra)
        return data

    def test_legacy_number_and_clauses_are_preserved_and_details_round_trip(self):
        before = self.client.get(self.url)
        self.assertContains(before, 'لم تُستكمل البيانات الداخلية')
        self.assertContains(before, self.agreement.number)
        self.assertFalse(AgreementDetails.objects.exists())
        response = self.client.post(self.url, self.payload(), follow=True)
        for phrase in ('2028-02-29', 'ضابط المؤسسة', 'ممثل الجهة', 'موقّع المؤسسة', 'موقّع الجهة', 'الكليات', 'التوظيف'):
            self.assertContains(response, phrase)
        for side in ('institution', 'partner'):
            self.assertEqual(self.agreement.members.filter(side=side).count(), 1)
        self.assertEqual(self.agreement.members.get(side='partner').phone, '0501234567')
        record = AgreementDetails.objects.get(agreement=self.agreement)
        self.assertEqual(record.responsible_employee, self.admin)
        self.assertEqual(record.initial_expiry, date(2028, 2, 29))
        self.assertEqual(self.agreement.clause_assignments.get().progress, 65)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.ends_on, date(2029, 5, 1))
        event = UserActivity.objects.get(description='تحديث بيانات الاتفاقية')
        self.assertEqual(event.after['agreement_expires_on'], '2028-02-29')
        self.assertNotIn('officer@example.org', str(event.after))

    def test_invalid_dates_reference_kinds_and_out_of_scope_staff_are_rejected_atomically(self):
        staff = self.limited('staff-outside', self.other_region, 'view')
        roster = self.client.get(self.url, {'edit': '1'}).context['form'].fields['responsible_employee'].queryset
        self.assertFalse(roster.filter(pk=staff.pk).exists())
        response = self.client.post(self.url, self.payload(
            duration_months='', classification=self.department.pk, responsible_employee=staff.pk,
            **{'partner-0-phone': '123x'},
        ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.context['form'].errors), {'duration_months', 'classification', 'responsible_employee'})
        self.assertFalse(AgreementDetails.objects.exists())
        self.assertFalse(AgreementMember.objects.exists())

    def test_renewal_needs_approval_is_contiguous_and_original_term_stays_locked(self):
        self.assertEqual(self.client.post(self.url, self.payload()).status_code, 302)
        signed = self.client.get(self.url).context['renew_token']
        data = {'operation': 'renew', 'snapshot': signed, 'renewal-duration_months': '12'}
        self.assertContains(self.client.post(self.url, data), 'أدخل مرجع الموافقة', status_code=400)
        self.assertFalse(AgreementRenewal.objects.exists())
        data['renewal-approval_reference'] = 'موافقة 14'
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        renewal = self.agreement.renewals.get()
        self.assertEqual((renewal.starts_on, renewal.expires_on), (date(2028, 2, 29), date(2029, 2, 28)))
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        self.assertTrue(self.client.get(self.url, {'edit': '1'}).context['form'].fields['signed_on'].disabled)
        self.assertContains(self.client.get(self.url), '2029-02-28')
        self.assertEqual(self.agreement.details.initial_expiry, date(2028, 2, 29))

    def test_preserves_other_team_and_rejects_cross_team_ids_and_stale_updates(self):
        data = self.payload()
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.assertEqual(self.client.post(self.url, data).status_code, 409)
        inside = self.agreement.members.get(side='institution')
        outside = self.agreement.members.get(side='partner')
        bad = self.payload(**{
            'institution-INITIAL_FORMS': '1', 'institution-0-id': str(outside.pk),
            'partner-INITIAL_FORMS': '1', 'partner-0-id': str(outside.pk),
        })
        self.assertEqual(self.client.post(self.url, bad).status_code, 400)
        valid = self.payload(**{
            'institution-INITIAL_FORMS': '1', 'institution-0-id': str(inside.pk), 'institution-0-DELETE': 'on',
            'partner-INITIAL_FORMS': '1', 'partner-0-id': str(outside.pk),
        })
        self.assertEqual(self.client.post(self.url, valid).status_code, 302)
        self.assertEqual(list(self.agreement.members.values_list('pk', flat=True)), [outside.pk])

    def test_guard_covers_read_only_overlap_cross_partnership_and_write_revocation(self):
        user = self.limited('agreement-editor', self.region, 'view', 'edit')
        self.client.force_login(user, backend='accounts.backends.EmailOrUsernameBackend')
        data = self.payload(responsible_employee=user.pk)
        self.partner.administrative_regions.add(self.other_region)
        self.assertContains(self.client.get(self.url), self.agreement.number)
        self.assertNotContains(self.client.get(self.url), 'تعديل بيانات الاتفاقية')
        self.assertEqual(self.client.post(self.url, data).status_code, 403)
        other = Partnership.objects.create(name='شراكة مزورة', entity=self.entity, scope='local')
        other.administrative_regions.add(self.region)
        wrong = reverse('partnerships:agreement_details', args=[other.pk, self.agreement.pk])
        self.assertEqual(self.client.get(wrong).status_code, 404)
        user.makken_access.allowed_regions.clear()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_reference_manager_can_add_edit_and_deactivate_without_removing_links(self):
        route = reverse('agreement_clauses:references')
        add = self.client.get(route + '?edit=new')
        self.assertEqual(self.client.post(route, {'operation': 'add', 'snapshot': add.context['token'],
                                                 'name': 'حالة جديدة'}).status_code, 302)
        new = AgreementOption.objects.get(kind='status', name='حالة جديدة')
        editor = self.client.get(route + f'?edit={new.pk}')
        self.assertEqual(self.client.post(route, {'operation': 'edit', 'snapshot': editor.context['token'],
            'name': 'حالة محدثة'}).status_code, 302)
        profile = AgreementDetails.objects.create(agreement=self.agreement, status=new)
        row_token = next(token for row, token in self.client.get(route).context['rows'] if row.pk == new.pk)
        self.assertEqual(self.client.post(route, {'operation': 'toggle', 'snapshot': row_token}).status_code, 302)
        self.assertEqual(self.client.post(route, {'operation': 'toggle', 'snapshot': row_token}).status_code, 409)
        new.refresh_from_db()
        self.assertFalse(new.is_active)
        profile.refresh_from_db()
        self.assertEqual(profile.status_id, new.pk)
        reader = self.limited('catalog-reader', self.region, 'view', module='agreement_clauses')
        self.client.force_login(reader, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(self.client.get(route).status_code, 200)
        self.assertEqual(self.client.get(route + '?edit=new').status_code, 403)
