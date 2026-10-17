from datetime import timedelta
from importlib import import_module
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection, IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from accounts.backends import EmailOrUsernameBackend
from accounts.models import UserProfile
from accounts.profile_forms import email_key

OLD='Before!Safe731Password'
NEW='Future!Secure942Password'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ProfileTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user('profile-user',email='profile@example.com',password=OLD,first_name='أحمد',last_name='محمد')
        self.other=get_user_model().objects.create_user('other-user',email='other@example.com',password=OLD)
        self.client.force_login(self.user, backend="accounts.backends.EmailOrUsernameBackend")
        self.url='/profile/'

    def page(self):return self.client.get(self.url)

    def details(self,**changes):
        values={'action':'details','snapshot':self.page().context['detail_form']['snapshot'].value(),'first_name':'أحمد','last_name':'محمد','email':'profile@example.com','email_confirm':'','phone_country':'SA','phone':'0501234567','current_password':OLD}
        values.update(changes);return values

    def password(self,**changes):
        values={'action':'password','snapshot':self.page().context['password_form']['snapshot'].value(),'old_password':OLD,'new_password1':NEW,'new_password2':NEW}
        values.update(changes);return values

    def seed_phone(self):
        return UserProfile.objects.create(user=self.user,phone_country='SA',phone='+966501234567',email_key=email_key(self.user.email))

    def test_login_methods_headers_get_no_write_and_query_count(self):
        self.assertEqual(Client().get(self.url).status_code,302)
        self.assertEqual(self.client.put(self.url).status_code,405)
        with CaptureQueriesContext(connection) as queries:response=self.page()
        self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(queries),6)
        self.assertFalse(UserProfile.objects.exists())
        self.assertIn('no-store',response['Cache-Control'])
        self.assertIn("script-src 'self'",response['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline',response['Content-Security-Policy'])
        self.assertContains(response,'profile-sidebar-link',count=2)
        self.assertNotContains(response,'value="IL"')
        self.assertContains(response,'تأكيد البريد الإلكتروني')
        self.assertContains(response,'تأكيد كلمة المرور الجديدة')

    def test_profile_success_normalizes_phone_and_only_self(self):
        response=self.client.post(self.url,self.details(first_name='  مروان  ',last_name='نوفل',user_id=self.other.pk,is_superuser='1',username='changed',is_active='0'))
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.other.refresh_from_db()
        self.assertEqual(self.user.first_name,'مروان');self.assertEqual(self.user.last_name,'نوفل')
        self.assertFalse(self.user.is_superuser);self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.username,'profile-user');self.assertEqual(self.other.first_name,'')
        info=UserProfile.objects.get(user=self.user)
        self.assertEqual(info.phone,'+966501234567');self.assertEqual(info.version,2)
        self.assertEqual(info.email_key,email_key(self.user.email))
        self.assertTrue(self.user.check_password(OLD))

    def test_names_only_do_not_require_current_password(self):
        self.seed_phone()
        response=self.client.post(self.url,self.details(first_name='اسم جديد',current_password=''))
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertEqual(self.user.first_name,'اسم جديد')

    def test_email_change_requires_matching_confirmation_and_current_password(self):
        for changes in [{'email':'new@example.com'},{'email':'new@example.com','email_confirm':'wrong@example.com'},{'email':'new@example.com','email_confirm':'new@example.com','current_password':''}]:
            response=self.client.post(self.url,self.details(**changes));self.assertEqual(response.status_code,400)
            self.user.refresh_from_db();self.assertEqual(self.user.email,'profile@example.com')
        response=self.client.post(self.url,self.details(email=' New@Example.COM ',email_confirm='new@example.com'))
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertEqual(self.user.email,'new@example.com')
        self.assertIsNotNone(EmailOrUsernameBackend().authenticate(None,username='NEW@example.com',password=OLD))
        self.assertIsNone(EmailOrUsernameBackend().authenticate(None,username='profile@example.com',password=OLD))

    def test_duplicate_emails_and_username_login_collisions_rejected(self):
        get_user_model().objects.create_user('collision@example.com',password=OLD)
        for email in ['OTHER@example.com','collision@example.com']:
            response=self.client.post(self.url,self.details(email=email,email_confirm=email))
            self.assertEqual(response.status_code,400);self.assertIn('email',response.context['detail_form'].errors)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_email_reservation_database_uniqueness(self):
        self.seed_phone()
        with self.assertRaises(IntegrityError),transaction.atomic():
            UserProfile.objects.create(user=self.other,email_key=email_key('PROFILE@example.com'))

    def test_invalid_phone_country_and_name(self):
        for changes in [{'phone':'123'},{'phone_country':'JO','phone':'0501234567'},{'phone_country':'IL'},{'phone':'+966501234567 ext 1'},{'first_name':'<script>alert(1)</script>'},{'last_name':'X'*151}]:
            self.assertEqual(self.client.post(self.url,self.details(**changes)).status_code,400)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_phone_change_requires_current_password_and_accepts_arabic_digits(self):
        response=self.client.post(self.url,self.details(current_password=''))
        self.assertEqual(response.status_code,400)
        response=self.client.post(self.url,self.details(phone='٠٥٠١٢٣٤٥٦٧'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(UserProfile.objects.get(user=self.user).phone,'+966501234567')

    def test_password_change_keeps_this_session_remember_me_and_logs_out_other(self):
        second=Client();second.force_login(self.user, backend="accounts.backends.EmailOrUsernameBackend")
        session=self.client.session;session.set_expiry(14*24*3600);session.save()
        old_key=self.client.session.session_key
        response=self.client.post(self.url,self.password())
        self.assertEqual(response.status_code,302)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password(NEW));self.assertFalse(self.user.check_password(OLD))
        self.assertIsNotNone(EmailOrUsernameBackend().authenticate(None,username=self.user.email,password=NEW))
        self.assertIsNone(EmailOrUsernameBackend().authenticate(None,username=self.user.email,password=OLD))
        self.assertNotEqual(self.client.session.session_key,old_key)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertGreater(self.client.session.get_expiry_age(),13*24*3600)
        self.assertEqual(self.page().status_code,200)
        self.assertEqual(second.get(self.url).status_code,302)

    def test_browser_close_session_expiry_is_preserved(self):
        session=self.client.session;session.set_expiry(0);session.save()
        self.assertEqual(self.client.post(self.url,self.password()).status_code,302)
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_password_policy_rejects_each_missing_rule_and_reuse(self):
        for value in ['Short!1','nouppercase!123','NOLOWERCASE!123','MissingNumber!!','MissingSpecial123','Contains space!123',OLD,'Strong!123\x00Other']:
            response=self.client.post(self.url,self.password(new_password1=value,new_password2=value))
            self.assertEqual(response.status_code,400,value)
        response=self.client.post(self.url,self.password(new_password2='Different!Secure942'))
        self.assertEqual(response.status_code,400);self.assertIn('new_password2',response.context['password_form'].errors)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password(OLD))

    def test_password_cannot_be_similar_to_username_or_personal_information(self):
        # Django's similarity validator compares long strings with user attributes.
        self.user.username='VeryLongSimilarUsername!123';self.user.save(update_fields=['username'])
        response=self.client.post(self.url,self.password(new_password1='VeryLongSimilarUsername!124',new_password2='VeryLongSimilarUsername!124'))
        self.assertEqual(response.status_code,400)

    def test_wrong_current_password_throttle_is_shared_persistent_and_resets(self):
        values=self.password(old_password='wrong')
        for n in range(5):self.assertEqual(self.client.post(self.url,values).status_code,429 if n==4 else 400)
        self.assertEqual(UserProfile.objects.get(user=self.user).password_failures,5)
        response=self.client.post(self.url,self.password())
        self.assertEqual(response.status_code,429);self.assertIn('Retry-After',response)
        UserProfile.objects.filter(user=self.user).update(password_locked_until=timezone.now()-timedelta(seconds=1),failure_window_started_at=timezone.now()-timedelta(minutes=16))
        self.assertEqual(self.client.post(self.url,self.password()).status_code,302)
        self.assertEqual(UserProfile.objects.get(user=self.user).password_failures,0)

    def test_wrong_contact_password_counts_and_never_echoes_passwords(self):
        response=self.client.post(self.url,self.details(current_password='ThisIsWrong!678'))
        self.assertEqual(response.status_code,400)
        self.assertNotContains(response,'ThisIsWrong!678',status_code=400)
        self.assertEqual(UserProfile.objects.get(user=self.user).password_failures,1)
        response=self.client.post(self.url,self.password(old_password='DifferentWrong!347',new_password1='Short!1',new_password2='Short!2'))
        self.assertNotContains(response,'DifferentWrong!347',status_code=400)
        self.assertNotContains(response,'Short!1',status_code=400)
        self.assertNotContains(response,'Short!2',status_code=400)

    def test_signed_form_prevents_replay_stale_and_cross_user_changes(self):
        values=self.details()
        self.assertEqual(self.client.post(self.url,values).status_code,302)
        self.assertEqual(self.client.post(self.url,values).status_code,409)
        values=self.details();values['snapshot']+='x'
        self.assertEqual(self.client.post(self.url,values).status_code,409)
        values=self.password();self.client.force_login(self.other, backend="accounts.backends.EmailOrUsernameBackend")
        self.assertEqual(self.client.post(self.url,values).status_code,409)

    def test_password_change_invalidates_old_profile_snapshot(self):
        details=self.details()
        self.assertEqual(self.client.post(self.url,self.password()).status_code,302)
        self.assertEqual(self.client.post(self.url,details).status_code,409)

    def test_csrf_and_oversized_requests(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user, backend="accounts.backends.EmailOrUsernameBackend")
        self.assertEqual(secure.post(self.url,self.details()).status_code,403)
        values=self.details();values['padding']='a'*17000
        self.assertEqual(self.client.post(self.url,values).status_code,400)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_html_validation_errors_and_offline_plain_form_submission(self):
        response=self.client.post(self.url,self.details(first_name='',email='invalid'))
        self.assertEqual(response.status_code,400);self.assertIn('first_name',response.context['detail_form'].errors)
        self.assertContains(response,'data-profile-errors',status_code=400)
        self.assertEqual(self.client.post(self.url,self.details()).status_code,302)

    def test_existing_email_reservations_migration_preserves_duplicates_and_users(self):
        a=get_user_model().objects.create_user('legacy-a',email='Duplicate@example.com')
        b=get_user_model().objects.create_user('legacy-b',email='duplicate@example.com')
        module=import_module('accounts.migrations.0001_initial')
        module.reserve_existing_emails(apps,connection.schema_editor())
        self.assertIsNone(UserProfile.objects.get(user=a).email_key)
        self.assertIsNone(UserProfile.objects.get(user=b).email_key)
        self.assertEqual(UserProfile.objects.get(user=self.user).email_key,email_key(self.user.email))
        self.assertEqual(get_user_model().objects.get(pk=a.pk).email,'Duplicate@example.com')
