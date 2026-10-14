from datetime import timedelta

from axes.models import AccessAttempt
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts.forms import INVALID_CREDENTIALS
from accounts.security import client_ip


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginTests(TestCase):
    password = "Existing-Password-123!"

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="marwan", email="marwan@example.com", password=self.password
        )

    def post(self, identifier="marwan", password=None, **data):
        return self.client.post("/login", {
            "username": identifier,
            "password": self.password if password is None else password,
            **data,
        })

    def test_exact_login_url_and_trailing_slash(self):
        for path in ("/login", "/login/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "جميع الحقوق محفوظة لـ © المؤسسة العامة للتدريب التقني والمهني، 2026")
            self.assertContains(response, "maxlength=\"254\"")

    def test_username_login(self):
        response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/")
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_real_django_pbkdf2_password_hash(self):
        user = self.User.objects.create_user("pbkdf", "pbkdf@example.com", self.password)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        response = self.post("pbkdf@example.com")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session[SESSION_KEY]), user.pk)

    def test_email_login_case_insensitive_and_trimmed(self):
        response = self.post("  MARWAN@EXAMPLE.COM  ")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session[SESSION_KEY]), self.user.pk)

    def test_regular_non_staff_user_can_log_in(self):
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.post().status_code, 302)

    def test_superuser_can_log_in_on_both_login_pages(self):
        self.User.objects.create_superuser(
            username="admin", email="admin@example.com", password=self.password
        )
        for path in ("/login", "/admin/login/"):
            self.client.logout()
            response = self.client.post(path, {
                "username": "admin", "password": self.password, "next": "/admin/",
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, "/admin/")

    def test_inactive_user_is_denied_with_generic_error(self):
        self.user.is_active = False
        self.user.save()
        response = self.post()
        self.assertContains(response, INVALID_CREDENTIALS)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_wrong_password_and_missing_user_same_message(self):
        for identifier in ("marwan", "no-such-user"):
            response = self.post(identifier, password="wrong")
            self.assertContains(response, INVALID_CREDENTIALS)
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_failed_response_does_not_echo_password(self):
        response = self.post(password="A-secret-not-to-echo!")
        self.assertNotContains(response, "A-secret-not-to-echo!")

    def test_duplicate_email_rejected_but_username_works(self):
        self.User.objects.create_user("other", "MARWAN@example.com", self.password)
        self.assertContains(self.post("marwan@example.com"), INVALID_CREDENTIALS)
        self.assertEqual(self.post("marwan").status_code, 302)

    def test_username_email_collision_rejected(self):
        self.User.objects.create_user("marwan@example.com", "other@example.com", self.password)
        self.assertContains(self.post("marwan@example.com"), INVALID_CREDENTIALS)

    def test_email_longer_than_username_model_limit(self):
        email = "test@" + "a" * 60 + "." + "b" * 60 + "." + "c" * 45 + ".com"
        self.user.email = email
        self.user.save()
        self.assertGreater(len(email), 150)
        self.assertEqual(self.post(email).status_code, 302)

    def test_existing_short_password_still_works(self):
        self.user.set_password("123")
        self.user.save()
        self.assertEqual(self.post(password="123").status_code, 302)

    def test_password_whitespace_not_trimmed(self):
        self.user.set_password(" valid password ")
        self.user.save()
        self.assertEqual(self.post(password=" valid password ").status_code, 302)

    def test_required_fields(self):
        response = self.post("", password="")
        self.assertContains(response, "أدخل البريد الإلكتروني أو اسم المستخدم.")
        self.assertContains(response, "أدخل كلمة المرور.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_null_characters_are_rejected(self):
        for identifier, password in (("marwan\x00", self.password), ("marwan", "pass\x00word")):
            response = self.post(identifier, password=password)
            self.assertContains(response, "تحتوي البيانات على محارف غير مسموح بها.")
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_oversized_fields_rejected(self):
        for identifier, password in (("x" * 255, self.password), ("marwan", "x" * 1025)):
            response = self.post(identifier, password=password)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(SESSION_KEY, self.client.session)

    def test_csrf_required_and_valid_token_succeeds(self):
        client = Client(enforce_csrf_checks=True)
        bad = client.post("/login", {"username": "marwan", "password": self.password})
        self.assertEqual(bad.status_code, 403)
        self.assertContains(bad, "تعذّر التحقق من أمان الطلب.", status_code=403)
        client.get("/login")
        token = client.cookies["csrftoken"].value
        response = client.post("/login", {
            "username": "marwan", "password": self.password, "csrfmiddlewaretoken": token,
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(token, client.cookies["csrftoken"].value)

    def test_login_rotates_session_id(self):
        session = self.client.session
        session["pre_login"] = True
        session.save()
        previous = session.session_key
        self.assertEqual(self.post().status_code, 302)
        self.assertNotEqual(previous, self.client.session.session_key)

    def test_external_and_insecure_next_urls_denied(self):
        for target in ("https://evil.example/", "//evil.example/", "javascript:alert(1)"):
            self.client.logout()
            response = self.post(next=target)
            self.assertEqual(response.url, "/")

    def test_same_host_next_url_allowed(self):
        response = self.post(next="/admin/")
        self.assertEqual(response.url, "/admin/")

    def test_https_login_rejects_http_next(self):
        response = self.client.post("/login", {
            "username": "marwan", "password": self.password, "next": "http://testserver/admin/",
        }, secure=True)
        self.assertEqual(response.url, "/")

    def test_escaping_identifier_in_html(self):
        response = self.post('"><script>alert(1)</script>', password="wrong")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_failed_attempt_lockout_shared_by_identifier(self):
        for index in range(4):
            self.assertEqual(self.post(f"unknown-{index}", password="wrong").status_code, 200)
        locked = self.post("marwan", password="wrong")
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked["Retry-After"], "900")
        self.assertContains(locked, "15 دقيقة", status_code=429)
        self.assertEqual(self.post().status_code, 429)
        other_ip = self.client.post("/login", {
            "username": "marwan", "password": self.password,
        }, REMOTE_ADDR="8.8.8.8")
        self.assertEqual(other_ip.status_code, 302)

    def test_lockout_expires(self):
        for _ in range(5):
            self.post(password="wrong")
        old = timezone.now() - timedelta(minutes=16)
        AccessAttempt.objects.update(attempt_time=old)
        self.assertEqual(self.post().status_code, 302)

    def test_success_resets_failed_attempts(self):
        for _ in range(4):
            self.post(password="wrong")
        self.assertEqual(self.post().status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.assertEqual(self.post(password="wrong").status_code, 200)

    def test_proxy_ip_and_untrusted_header(self):
        factory = RequestFactory()
        trusted = factory.get("/login", REMOTE_ADDR="172.18.0.1", HTTP_X_REAL_IP="1.1.1.1")
        untrusted = factory.get("/login", REMOTE_ADDR="8.8.8.8", HTTP_X_REAL_IP="1.1.1.1")
        self.assertEqual(client_ip(trusted), "1.1.1.1")
        self.assertEqual(client_ip(untrusted), "8.8.8.8")

    def test_security_headers(self):
        response = self.client.get("/login")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", response["Content-Security-Policy"])

    def test_logout_requires_post_and_csrf(self):
        self.post()
        self.assertEqual(self.client.get("/logout").status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user, backend="accounts.backends.EmailOrUsernameBackend")
        self.assertEqual(client.post("/logout").status_code, 403)
        client.get("/login")
        response = client.post("/logout", {
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/login")
        self.assertNotIn(SESSION_KEY, client.session)

    def test_oversized_request_body_is_rejected(self):
        response = self.client.post("/login", {"username": "x" * 20000, "password": "wrong"})
        self.assertEqual(response.status_code, 400)

    def test_authenticated_login_form_remains_available(self):
        self.post()
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_authenticated_session_expires_on_browser_close(self):
        self.post()
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.assertEqual(self.client.session.get_expiry_age(), 3600)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_https_cookie_flags(self):
        response = self.client.post("/login", {
            "username": "marwan", "password": self.password,
        }, secure=True)
        self.assertTrue(response.cookies["sessionid"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(response.cookies["sessionid"]["samesite"], "Lax")
        self.assertTrue(response.cookies["csrftoken"]["secure"])
