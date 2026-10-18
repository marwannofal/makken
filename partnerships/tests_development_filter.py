from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase

from care_states.models import DevelopmentState, StateColor, DEFAULT_COLORS
from entities.models import Entity
from .models import Partnership


class DevelopmentFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="state-filter-user")
        cls.entity = Entity.objects.create(name="كيان اختبار التصفية", entity_type="government")
        for key, label in DevelopmentState.choices:
            StateColor.objects.get_or_create(state=key, defaults={"color": DEFAULT_COLORS[key]})
            Partnership.objects.create(
                name="جهة " + label, representative="ممثل", phone_country="SA",
                phone="+966501234567", email="filter@example.com", entity=cls.entity,
                scope="local", development_state_id=key, financial_capacity=Decimal("500"),
            )

    def setUp(self):
        self.client.force_login(self.user)

    def test_all_three_arabic_url_values_filter_existing_states(self):
        for key, label in DevelopmentState.choices:
            with self.subTest(state=key):
                response = self.client.get("/partnerships/", {"development_state": label})
                self.assertEqual(response.status_code, 200)
                expected = {"willingness", "capability"} if key == "willingness" else {key}
                self.assertEqual({r["item"].development_state_id for r in response.context["rows"]}, expected)
                self.assertEqual(response.context["development_filter_form"]["development_state"].value(), label)
                self.assertEqual(parse_qs(response.context["result_query"])["development_state"], [label])

    def test_empty_filter_shows_all_and_reset_removes_filter(self):
        for params in ({}, {"development_state": ""}):
            response = self.client.get("/partnerships/", params)
            self.assertEqual(len(response.context["rows"]), 3)
            self.assertNotIn("development_state", parse_qs(response.context["result_query"]))
        choices = list(response.context["development_filter_form"].fields["development_state"].choices)
        self.assertEqual([value for value, _ in choices if value], ["قدرة", "رغبة", "رعاية"])
        self.assertContains(response, 'href="/partnerships/">مسح</a>')

    def test_filter_combines_with_search_status_and_financial_range(self):
        item = Partnership.objects.get(development_state_id="care")
        response = self.client.get("/partnerships/", {"development_state": "رعاية", "q": "جهة", "status": "1", "capacity_min": "500", "capacity_max": "500"})
        self.assertEqual([r["item"].pk for r in response.context["rows"]], [item.pk])
        item.is_active = False
        item.save(update_fields=["is_active"])
        response = self.client.get("/partnerships/", {"development_state": "رعاية", "status": "1"})
        self.assertEqual(len(response.context["rows"]), 0)
        self.assertContains(response, "لا توجد نتائج")

    def test_invalid_state_does_not_silently_show_all_or_render_payload(self):
        for value in ("invalid", "willingness", '<script>alert(1)</script>'):
            response = self.client.get("/partnerships/", {"development_state": value})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(len(response.context["rows"]), 0)
            self.assertTrue(response.context["development_filter_form"].errors)
            self.assertNotContains(response, "<script>alert(1)</script>", status_code=400)

    def test_pagination_details_and_close_url_keep_filters(self):
        original = Partnership.objects.get(development_state_id="willingness")
        for i in range(17):
            Partnership.objects.create(name=f"جهة رغبة {i}", representative="ممثل", phone_country="SA", phone="+966501234567", email="filter@example.com", entity=self.entity, scope="local", development_state_id="willingness", financial_capacity=500)
        params = {"development_state": "رغبة", "q": "جهة", "status": "1", "capacity_min": "400", "page": "2"}
        response = self.client.get("/partnerships/", params)
        self.assertEqual(response.context["page_obj"].paginator.count, 19)
        self.assertEqual(len(response.context["rows"]), 4)
        self.assertEqual(parse_qs(response.context["financial_pagination_query"])["development_state"], ["رغبة"])
        response = self.client.get("/partnerships/", {**params, "detail": original.pk})
        close = parse_qs(urlsplit(response.context["list_url"]).query)
        self.assertEqual(close["development_state"], ["رغبة"])
        self.assertEqual(close["page"], ["2"])
        self.assertEqual(close["capacity_min"], ["400.00"])

    def test_confirmed_row_action_redirect_preserves_state_and_other_filters(self):
        params = {"development_state": "قدرة", "status": "1", "capacity_min": "400", "page": "1"}
        path = "/partnerships/?" + urlencode(params)
        row = self.client.get(path).context["rows"][0]
        preview = self.client.post(path, {"action": "preview", "token": row["toggle"]})
        response = self.client.post(path, {"action": "confirm", "token": preview.context["pending"]["token"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(parse_qs(urlsplit(response.url).query), {k: [v] for k, v in params.items()})

    def test_filter_get_never_changes_state_timestamp_or_history(self):
        before = list(Partnership.objects.values_list("pk", "development_state_id", "development_state_at", "version"))
        for label in ("قدرة", "رغبة", "رعاية"):
            self.client.get("/partnerships/", {"development_state": label})
        self.assertEqual(list(Partnership.objects.values_list("pk", "development_state_id", "development_state_at", "version")), before)

    def test_login_required(self):
        self.client.logout()
        response = self.client.get("/partnerships/", {"development_state": "رغبة"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login"))
