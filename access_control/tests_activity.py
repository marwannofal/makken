"""Real authorization, committed mutations, regional snapshots and documents."""
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
import json
from unittest.mock import patch
from zipfile import ZipFile
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, RequestFactory, Client
from django.urls import reverse
from access_control.defaults import initialize
from access_control.models import UserActivity, ActivityRegion, UserAccess, PermissionOverride, RoleProfile, SecurityAudit
from access_control.activity_capture import current, Capture, emit
from access_control.activity_data import visible_events, sanitize, decorate_event
from access_control.activity_history import import_history
from access_control.activity_forms import ActivityFilterForm
from market_needs.tests.test_market import MarketFixtures
from market_needs.models import Need, AuditEvent
from partnerships.models import Partnership
from regions.models import Region


class ActivityTests(MarketFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        initialize()
        cls.reader = get_user_model().objects.create_user('activity-reader',password='Safe!Activity123')
        cls.regional = get_user_model().objects.create_user('activity-regional',password='Safe!Activity124')
        for user in [cls.reader, cls.regional]:
            UserAccess.objects.create(user=user,page_scope='all',region_scope='selected' if user==cls.regional else 'all')
            PermissionOverride.objects.create(user=user,module_id='user_activity',operation='view',effect='grant')
        cls.regional.makken_access.allowed_regions.add(cls.region)

    def login_user(self,user=None):
        self.client.force_login(user or self.reader,backend='accounts.backends.EmailOrUsernameBackend')

    @contextmanager
    def capture(self,actor=None):
        request=RequestFactory().post('/partnerships/new/')
        request.user=actor or self.user
        ctx=Capture(request);token=current.set(ctx)
        try:
            yield ctx
        finally:
            current.reset(token)

    def event(self,regions=None,**kwargs):
        return emit(actor=self.user,module='partnerships',action='update',description='تعديل جهة',
                    target_label='AUDIT_VISIBLE',regions=regions or {},**kwargs)

    def grant_export(self,format='xlsx'):
        PermissionOverride.objects.create(user=self.reader,module_id='user_activity',operation='export_'+format,effect='grant')

    def test_new_sensitive_module_never_grants_default_roles(self):
        for key in ['watcher','editor']:
            self.assertFalse(RoleProfile.objects.get(system_key=key).group.permissions.filter(codename__endswith='_user_activity').exists())
        self.assertTrue(Permission.objects.filter(codename='export_pdf_user_activity').exists())

    def test_page_and_detail_require_explicit_view_and_no_admin_management(self):
        e=self.event();self.login_user()
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,200)
        self.assertEqual(self.client.get(reverse('access_control:activity_detail',args=[e.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('access_control:index')).status_code,403)
        PermissionOverride.objects.filter(user=self.reader).delete()
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,403)
        self.assertEqual(self.client.get(reverse('access_control:activity_detail',args=[e.pk])).status_code,403)

    def test_anonymous_redirect_and_read_only_methods(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,302)
        self.login_user(self.user)
        self.assertEqual(self.client.post(reverse('access_control:activity')).status_code,405)

    def test_explicit_denial_page_scope_and_revocation_apply_immediately(self):
        self.login_user()
        a=UserAccess.objects.get(user=self.reader);a.page_scope='selected';a.save()
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,403)
        a.allowed_pages.add('user_activity')
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,200)
        PermissionOverride.objects.filter(user=self.reader).update(effect='deny')
        self.assertEqual(self.client.get(reverse('access_control:activity')).status_code,403)

    def test_region_boundary_requires_all_historical_regions(self):
        own=self.event(regions={self.region.pk:self.region.name})
        shared=self.event(regions={self.region.pk:self.region.name,self.region2.pk:self.region2.name})
        hidden=self.event(regions={self.region2.pk:self.region2.name})
        general=self.event()
        self.assertEqual(set(visible_events(self.regional).values_list('pk',flat=True)),{own.pk})
        self.login_user(self.regional)
        for item in [shared,hidden,general]:
            self.assertEqual(self.client.get(reverse('access_control:activity_detail',args=[item.pk])).status_code,404)
        self.assertEqual(self.client.get(reverse('access_control:activity'),{'region':self.region2.pk}).context['page_obj'].paginator.count,0)

    def test_scope_survives_region_rename_and_unassigned_history_is_hidden(self):
        e=self.event(regions={self.region.pk:self.region.name})
        old=e.region_snapshots.get().name
        Region.objects.filter(pk=self.region.pk).update(name='اسم جديد')
        self.assertEqual(e.region_snapshots.get().name,old)
        unknown=self.event(scope='unknown')
        self.assertFalse(visible_events(self.regional).filter(pk=unknown.pk).exists())

    def test_date_and_exact_time_filters_use_saudi_timezone(self):
        self.event(created_at=datetime(2026,11,7,21,0,0,tzinfo=timezone.utc))
        self.event(created_at=datetime(2026,11,8,20,59,59,tzinfo=timezone.utc))
        self.event(created_at=datetime(2026,11,8,21,0,0,tzinfo=timezone.utc))
        self.login_user()
        page=self.client.get(reverse('access_control:activity'),{'date_from':'2026-11-08','date_to':'2026-11-08'})
        self.assertEqual(page.context['page_obj'].paginator.count,2)
        page=self.client.get(reverse('access_control:activity'),{'date_from':'2026-11-08','time_from':'23:59:59','date_to':'2026-11-08','time_to':'23:59:59'})
        self.assertEqual(page.context['page_obj'].paginator.count,1)

    def test_invalid_dates_times_and_choices_fail_closed(self):
        self.event();self.login_user()
        for data in [{'date_from':'2026-19-80'},{'time_from':'14:00'},
                     {'date_from':'2026-11-10','date_to':'2026-11-08'},
                     {'region':'999999'},{'actor':'999999'},{'action':'sql'},{'q':'x'*201}]:
            with self.subTest(data=data):
                response=self.client.get(reverse('access_control:activity'),data)
                self.assertEqual(response.context['page_obj'].paginator.count,0)
                self.assertTrue(response.context['form'].errors)

    def test_search_module_action_outcome_and_actor(self):
        e=self.event()
        self.login_user()
        page=self.client.get(reverse('access_control:activity'),{'q':'AUDIT_VISIBLE','module':'partnerships','action':'update','actor':self.user.pk,'outcome':'success'})
        self.assertEqual([x.pk for x in page.context['rows']],[e.pk])

    def test_dropdowns_do_not_leak_users_from_hidden_events(self):
        self.event(regions={self.region2.pk:self.region2.name})
        self.login_user(self.regional)
        response=self.client.get(reverse('access_control:activity'))
        self.assertNotIn(self.user.pk,dict(response.context['form'].fields['actor'].choices))
        self.assertNotIn(self.region2.pk,dict(response.context['form'].fields['region'].choices))

    def test_real_committed_create_update_status_delete_and_regions(self):
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                org=self.organization(name='AUDITED_CREATE')
                org.administrative_regions.add(self.region)
        event=UserActivity.objects.get(target_model='partnerships.partnership',target_key=str(org.pk))
        self.assertEqual(event.action,'create')
        self.assertEqual(list(event.region_snapshots.values_list('region_key',flat=True)),[self.region.pk])
        for change,expected in [('name','update'),('is_active','status')]:
            with self.captureOnCommitCallbacks(execute=True),self.capture():
                with transaction.atomic():
                    setattr(org,change,'AUDITED_EDIT' if change=='name' else False);org.save()
            self.assertEqual(UserActivity.objects.first().action,expected)
        key=str(org.pk)
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            org.delete()
        event=UserActivity.objects.filter(target_model='partnerships.partnership',target_key=key).first()
        self.assertEqual(event.action,'delete')
        self.assertTrue(visible_events(self.regional).filter(pk=event.pk).exists())

    def test_rollback_and_unchanged_save_do_not_create_events(self):
        org=self.organization()
        count=UserActivity.objects.count()
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            try:
                with transaction.atomic():
                    org.name='ROLLED_BACK';org.save();raise ValueError('rollback')
            except ValueError:pass
        self.assertEqual(UserActivity.objects.count(),count)
        org.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            org.save()
        self.assertEqual(UserActivity.objects.count(),count)

    def test_region_move_remembers_both_sides(self):
        org=self.organization();org.administrative_regions.add(self.region)
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                org.administrative_regions.set([self.region2])
        event=UserActivity.objects.first()
        self.assertEqual(set(event.region_snapshots.values_list('region_key',flat=True)),{self.region.pk,self.region2.pk})
        self.assertFalse(visible_events(self.regional).filter(pk=event.pk).exists())

    def test_private_profile_changes_record_flags_without_values(self):
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                self.reader.email='PRIVATE_EMAIL@example.test'
                self.reader.set_password('PRIVATE_PASSWORD832!');self.reader.save()
        events=UserActivity.objects.filter(target_model='auth.user')
        self.assertEqual(events.count(),1)
        raw=json.dumps(events.first().after)
        self.assertIn('password_changed',raw);self.assertIn('email_changed',raw)
        self.assertNotIn('PRIVATE',raw);self.assertNotIn('pbkdf2',raw);self.assertNotIn('md5',raw)

    def test_capture_only_on_commit_after_final_owned_data(self):
        org=self.organization();org.administrative_regions.add(self.region)
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                org.name='FIRST_SAVE';org.save();org.name='FINAL_SAVE';org.save()
        rows=UserActivity.objects.filter(target_model='partnerships.partnership')
        self.assertEqual(rows.count(),1)
        self.assertEqual(rows.first().after['name'],'FINAL_SAVE')

    def test_source_audit_prevents_duplicate_generic_events(self):
        need=self.create_need()
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                need.title='SOURCE_UPDATED';need.save()
                source=AuditEvent.objects.create(need=need,need_number=need.number,actor=self.user,
                    action='تعديل البطاقة',before={'title':'OLD'},after={'title':'SOURCE_UPDATED'})
        self.assertEqual(UserActivity.objects.filter(target_key=str(need.pk),module='market_needs').count(),1)
        self.assertTrue(UserActivity.objects.filter(source_key=f'history:market_needs.auditevent:{source.pk}').exists())

    def test_historical_import_is_idempotent_and_does_not_invent_views(self):
        source=SecurityAudit.objects.create(actor=self.user,actor_name='ORIGINAL_ACTOR',target_name='هدف',action='تغيير كلمة مرور',
            before={'password':'PRIVATE_HASH','token':'PRIVATE_TOKEN'},after={'email':'PRIVATE_EMAIL'})
        import_history();count=UserActivity.objects.count();import_history()
        self.assertEqual(UserActivity.objects.count(),count)
        e=UserActivity.objects.get(source_key=f'history:access_control.securityaudit:{source.pk}')
        self.assertEqual(e.before,{});self.assertEqual(e.after,{'email_changed':True})
        self.assertEqual(e.created_at,source.created_at)
        self.assertFalse(UserActivity.objects.filter(action='view').exists())

    def test_deleted_actor_identity_snapshot_is_retained(self):
        reader=get_user_model().objects.create_user('deleted-audit-user')
        e=emit(actor=reader,module='accounts',action='login',description='دخول')
        pk=reader.pk;reader.delete();e.refresh_from_db()
        self.assertIsNone(e.actor_id);self.assertEqual(e.actor_key,pk)
        self.assertEqual(e.actor_username,'deleted-audit-user')

    def test_html_and_detail_escape_values_and_exclude_sensitive_keys(self):
        e=self.event(before={'name':'<script>alert(1)</script>','password':'PRIVATE'},after={'name':'<img src=x onerror=alert(1)>','csrf_token':'PRIVATE'})
        self.login_user()
        response=self.client.get(reverse('access_control:activity_detail',args=[e.pk]),HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response,'&lt;script&gt;')
        self.assertNotContains(response,'<script>alert(1)')
        self.assertNotContains(response,'PRIVATE')

    def test_successful_views_denials_and_preview_do_not_look_like_edits(self):
        self.login_user()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get(reverse('access_control:activity'))
            self.client.get(reverse('regions:index'))
        self.assertTrue(UserActivity.objects.filter(action='view').exists())
        self.assertTrue(UserActivity.objects.filter(action='denied').exists())
        self.assertFalse(UserActivity.objects.filter(action__in=['update','create']).exists())

    def test_filter_errors_cannot_export_everything(self):
        self.event();self.login_user();self.grant_export()
        response=self.client.get(reverse('access_control:activity'),{'_mk_export':'xlsx','date_from':'bad'})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('attachment',response.get('Content-Disposition',''))

    def test_export_requires_separate_right_for_each_format(self):
        self.event();self.login_user()
        for fmt in ['xlsx','pdf']:
            self.assertEqual(self.client.get(reverse('access_control:activity'),{'_mk_export':fmt}).status_code,403)
        self.grant_export('xlsx')
        self.assertEqual(self.client.get(reverse('access_control:activity'),{'_mk_export':'pdf'}).status_code,403)

    def test_xlsx_all_pages_rtl_filters_formula_safety_and_single_export_event(self):
        for i in range(31):self.event(target_key=str(i),after={'name':'=PRIVATE_FORMULA'+str(i)})
        self.login_user();self.grant_export()
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.get(reverse('access_control:activity'),{'_mk_export':'xlsx','module':'partnerships','page':'2'})
        self.assertEqual(response.status_code,200)
        with ZipFile(BytesIO(response.content)) as z:
            xml=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        self.assertIn('rightToLeft="1"',xml)
        self.assertIn('PRIVATE_FORMULA0',xml);self.assertIn('PRIVATE_FORMULA30',xml)
        self.assertNotIn('<f>',xml)
        self.assertEqual(UserActivity.objects.filter(action='export_xlsx').count(),1)
        self.assertEqual(UserActivity.objects.filter(action='view').count(),0)

    def test_pdf_is_real_branded_document(self):
        self.event();self.login_user();self.grant_export('pdf')
        response=self.client.get(reverse('access_control:activity'),{'_mk_export':'pdf'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b'%PDF-'))
        from pypdf import PdfReader
        document=PdfReader(BytesIO(response.content));self.assertGreater(len(document.pages),0)

    def test_pagination_retains_all_filters_and_watermark(self):
        for i in range(27):self.event()
        self.login_user()
        response=self.client.get(reverse('access_control:activity'),{'module':'partnerships','action':'update','date_from':'2020-01-01'})
        self.assertContains(response,'module=partnerships')
        self.assertContains(response,'action=update')
        self.assertContains(response,'until=')
        self.assertEqual(response.context['page_obj'].paginator.count,27)

    def test_lower_watermark_excludes_new_records(self):
        first=self.event();self.event()
        self.login_user()
        response=self.client.get(reverse('access_control:activity'),{'until':first.pk})
        self.assertEqual([x.pk for x in response.context['rows']],[first.pk])

    def test_csrf_is_still_enforced(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(client.post(reverse('access_control:activity')).status_code,403)

    def test_real_authentication_signals_preserve_login_and_logout_actor(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.force_login(self.reader,backend='accounts.backends.EmailOrUsernameBackend')
            self.client.logout()
        self.assertEqual(set(UserActivity.objects.filter(actor_key=self.reader.pk).values_list('action',flat=True)),{'login','logout'})

    def test_failed_and_head_responses_never_count_as_successful_views(self):
        self.login_user()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.head(reverse('access_control:activity'))
            self.client.get(reverse('access_control:activity_detail',args=[999999]))
        self.assertFalse(UserActivity.objects.filter(action='view').exists())

    def test_source_snapshot_sensitive_data_and_historical_actor_preserved(self):
        source=SecurityAudit.objects.create(actor=None,actor_name='HISTORICAL_NAME',target_name='حساب سابق',action='تعديل',before={},after={})
        import_history()
        self.assertEqual(UserActivity.objects.get(source_key=f'history:access_control.securityaudit:{source.pk}').actor_name,'HISTORICAL_NAME')

    def test_role_change_is_audited_without_editing_profile_fields(self):
        role=RoleProfile.objects.get(system_key='watcher')
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                self.reader.groups.add(role.group)
        event=UserActivity.objects.get(target_model='auth.user',target_key=str(self.reader.pk))
        self.assertIn(role.group.name,event.after['roles'])

    def test_export_permission_does_not_imply_view_permission(self):
        self.grant_export()
        PermissionOverride.objects.filter(user=self.reader,operation='view').delete()
        self.login_user()
        self.assertEqual(self.client.get(reverse('access_control:activity'),{'_mk_export':'xlsx'}).status_code,403)

    def test_regional_export_cannot_leak_hidden_events(self):
        self.event(regions={self.region.pk:self.region.name},target_key='OWN_VISIBLE')
        self.event(regions={self.region2.pk:self.region2.name},target_key='PRIVATE_OTHER_REGION')
        PermissionOverride.objects.create(user=self.regional,module_id='user_activity',operation='export_xlsx',effect='grant')
        self.login_user(self.regional)
        response=self.client.get(reverse('access_control:activity'),{'_mk_export':'xlsx'})
        with ZipFile(BytesIO(response.content)) as z:
            xml=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        self.assertIn('OWN_VISIBLE',xml)
        self.assertNotIn('PRIVATE_OTHER_REGION',xml)

    def test_download_event_scopes_both_the_need_and_organization(self):
        from django.core.files.base import ContentFile
        from market_needs.models import SupportAttachment, Sponsorship
        need=self.create_need(regions=[str(self.region.pk)])
        org=self.organization();org.administrative_regions.add(self.region2)
        sponsor=Sponsorship.objects.create(need=need,partnership=org)
        attachment=SupportAttachment.objects.create(sponsorship=sponsor,file=ContentFile(b'%PDF-test',name='test.pdf'),original_name='test.pdf',size=9,content_type='application/pdf',uploaded_by=self.user)
        self.login_user(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.get(reverse('market_needs:download',args=[need.pk,attachment.pk]))
            self.assertEqual(b''.join(response.streaming_content),b'%PDF-test')
        event=UserActivity.objects.get(action='download')
        self.assertEqual(set(event.region_snapshots.values_list('region_key',flat=True)),{self.region.pk,self.region2.pk})
        self.assertFalse(visible_events(self.regional).filter(pk=event.pk).exists())

    def test_export_upper_bound_is_stable_across_synthetic_pages(self):
        from core.table_exports import TableExportMiddleware
        from access_control.activity_views import activity
        for i in range(31):self.event(target_key=f'ORIGINAL-{i}')
        self.login_user();self.grant_export()
        original=TableExportMiddleware.clone
        state={'inserted':False}
        def clone(request,page_key=None,page_number=None):
            if page_key and not state['inserted']:
                self.event(target_key='LATE-PRIVATE-ROW');state['inserted']=True
            return original(request,page_key,page_number)
        with patch.object(TableExportMiddleware,'clone',side_effect=clone):
            response=self.client.get(reverse('access_control:activity'),{'_mk_export':'xlsx'})
        self.assertTrue(state['inserted'])
        with ZipFile(BytesIO(response.content)) as z:
            xml=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        self.assertNotIn('LATE-PRIVATE-ROW',xml)
        self.assertIn('ORIGINAL-0',xml);self.assertIn('ORIGINAL-30',xml)

    def test_color_confirmation_logs_bulk_update_but_preview_does_not(self):
        self.login_user(self.user)
        url=reverse('care_states:index')
        page=self.client.get(url);row=page.context['rows'][0]
        with self.captureOnCommitCallbacks(execute=True):
            preview=self.client.post(url,{'action':'preview','state':row['state'],'color':'#123456','snapshot':row['snapshot']})
        self.assertFalse(UserActivity.objects.filter(module='care_states',action='update').exists())
        with self.captureOnCommitCallbacks(execute=True):
            response=self.client.post(url,{'action':'confirm','token':preview.context['pending']['token']})
        self.assertEqual(response.status_code,302)
        event=UserActivity.objects.get(module='care_states',action='update')
        self.assertEqual(event.after['color'],'#123456')

    def test_program_expense_relations_are_in_change_details(self):
        old=self.program.expense_items.count()
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                self.program.expense_items.clear()
        event=UserActivity.objects.get(target_model='training_programs.trainingprogram')
        self.assertEqual(len(event.before['expense_items']),old)
        self.assertEqual(event.after['expense_items'],[])

    def test_profile_phone_change_is_a_flag_not_a_number(self):
        from accounts.models import UserProfile
        profile=UserProfile.objects.create(user=self.reader,phone='+966501234567')
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            with transaction.atomic():
                profile.phone='+962798765432';profile.save()
        event=UserActivity.objects.get(target_model='accounts.userprofile')
        self.assertEqual(event.after,{'phone_changed':True})

    def test_rolled_back_source_does_not_suppress_a_later_committed_write(self):
        need=self.create_need()
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            try:
                with transaction.atomic():
                    AuditEvent.objects.create(need=need,need_number=need.number,actor=self.user,action='تعديل ملغى')
                    raise ValueError('rollback')
            except ValueError:pass
            with transaction.atomic():
                need.title='COMMITTED_AFTER_RETRY';need.save()
        event=UserActivity.objects.get(target_model='market_needs.need',target_key=str(need.pk))
        self.assertEqual(event.after['title'],'COMMITTED_AFTER_RETRY')

    def test_rolled_back_private_change_is_not_reported_as_committed(self):
        with self.captureOnCommitCallbacks(execute=True),self.capture():
            try:
                with transaction.atomic():
                    self.reader.email='NOT_COMMITTED@example.test';self.reader.save()
                    raise ValueError('rollback')
            except ValueError:pass
            self.reader.refresh_from_db()
            with transaction.atomic():
                self.reader.first_name='COMMITTED';self.reader.save()
        event=UserActivity.objects.get(target_model='auth.user',target_key=str(self.reader.pk))
        self.assertNotIn('email_changed',event.after)
        self.assertEqual(event.after['first_name'],'COMMITTED')
