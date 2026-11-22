"""Comprehensive unit & integration tests for site-wide centered pill pagination & per-page selector."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.test import RequestFactory, TestCase

from core.pagination import ALLOWED_PAGE_SIZES, resolve_page_size
from core.templatetags.makken_pagination import makken_pagination
from regions.models import Region
from levels.models import Level
from sectors.models import Sector
from entities.models import Entity
from care_states.models import StateColor
from partnerships.models import Partnership


class ResolvePageSizeTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_defaults_when_missing_or_none(self):
        self.assertEqual(resolve_page_size(None, 15), 15)
        self.assertEqual(resolve_page_size(self.rf.get("/"), 10), 10)
        self.assertEqual(resolve_page_size(self.rf.get("/"), 25), 25)

    def test_accepts_only_allowed_page_sizes(self):
        for size in ALLOWED_PAGE_SIZES:
            req = self.rf.get("/", {"per_page": str(size)})
            self.assertEqual(resolve_page_size(req, 15), size)

    def test_rejects_invalid_or_out_of_bounds_values(self):
        for bad in ["", "0", "-10", "5", "15", "25", "99", "1000", "abc", "10;DROP"]:
            req = self.rf.get("/", {"per_page": bad})
            self.assertEqual(resolve_page_size(req, 15), 15, f"Failed for {bad!r}")

    def test_supports_custom_param_name(self):
        req = self.rf.get("/", {"group_per_page": "50", "per_page": "10"})
        self.assertEqual(resolve_page_size(req, 15, param="group_per_page"), 50)
        self.assertEqual(resolve_page_size(req, 15, param="per_page"), 10)


class PaginationTagLogicTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_elided_range_preserves_filters_and_strips_detail(self):
        items = list(range(1, 201))
        page_obj = Paginator(items, 10).get_page(5)
        req = self.rf.get("/partnerships/capability/", {"q": "سابك", "per_page": "10", "page": "5", "detail": "99"})
        ctx = makken_pagination({"request": req}, page_obj)
        self.assertEqual(ctx["current_per_page"], 10)
        self.assertEqual(ctx["size_choices"], (10, 20, 50, 100))
        self.assertIn("page=4", ctx["prev_url"])
        self.assertIn("page=6", ctx["next_url"])
        self.assertNotIn("detail=", ctx["next_url"])
        self.assertIn("per_page=10", ctx["next_url"])
        urls_by_size = {o["size"]: o["url"] for o in ctx["size_options"]}
        self.assertIn("per_page=50", urls_by_size[50])
        self.assertIn("q=", urls_by_size[50])
        from urllib.parse import parse_qs
        qs = parse_qs(urls_by_size[50].lstrip("?"))
        self.assertEqual(qs.get("per_page"), ["50"])
        self.assertNotIn("page", qs)
        self.assertNotIn("detail", qs)
        types = [item["type"] for item in ctx["page_items"]]
        self.assertIn("ellipsis", types)
        currents = [item["number"] for item in ctx["page_items"] if item.get("current")]
        self.assertEqual(currents, [5])


class SiteWidePaginationIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="pg-admin",
            email="pg-admin@example.com",
            password="Makken!SafePass991",
            is_superuser=True,
            is_staff=True,
        )
        for state, color in [("capability", "#ba1d1d"), ("willingness", "#fdd2cf"), ("care", "#1c5d34")]:
            StateColor.objects.update_or_create(state=state, defaults={"color": color})
        cls.entity = Entity.objects.create(name="كيان الترقيم", entity_type="government", branch="")
        for i in range(25):
            Region.objects.create(name=f"منطقة ترقيم {i:02d}")
            Level.objects.create(name=f"مستوى ترقيم {i:02d}")
            Sector.objects.create(name=f"قطاع ترقيم {i:02d}")
            Partnership.objects.create(
                name=f"شراكة ترقيم {i:02d}",
                representative="الممثل",
                phone="+966501234567",
                email=f"p{i}@example.com",
                entity=cls.entity,
                scope="local",
                financial_capacity=1000,
                is_active=True,
                development_state_id="capability",
            )

    def setUp(self):
        self.client.force_login(self.user, backend="accounts.backends.EmailOrUsernameBackend")

    def test_regions_per_page_10_20_50_100_and_centered_ui(self):
        for size in (10, 20, 50, 100):
            res = self.client.get("/settings/regions/", {"per_page": str(size)})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.context["page_obj"].paginator.per_page, size)
            self.assertContains(res, "mk-pagination-wrap")
            self.assertContains(res, "عدد السجلات")
            self.assertContains(res, "data-no-search-select")
            self.assertContains(res, f'value="{size}"')
            self.assertNotContains(res, '<form method="get" class="mk-per-page-form"')

    def test_partnerships_capability_pagination_and_per_page(self):
        res_default = self.client.get("/partnerships/capability/")
        self.assertEqual(res_default.status_code, 200)
        self.assertEqual(res_default.context["page_obj"].paginator.per_page, 15)
        self.assertContains(res_default, "mk-pagination-wrap")
        self.assertContains(res_default, "عدد السجلات")

        res_10 = self.client.get("/partnerships/capability/", {"per_page": "10"})
        self.assertEqual(res_10.context["page_obj"].paginator.per_page, 10)
        self.assertEqual(len(res_10.context["page_obj"]), 10)
        self.assertGreaterEqual(res_10.context["page_obj"].paginator.num_pages, 3)
        self.assertContains(res_10, "per_page=10&amp;page=2")

        res_50 = self.client.get("/partnerships/capability/", {"per_page": "50"})
        self.assertEqual(res_50.context["page_obj"].paginator.per_page, 50)
        self.assertEqual(res_50.context["page_obj"].paginator.num_pages, 1)

    def test_major_table_pages_render_200_with_pagination_assets(self):
        paths = [
            "/partnerships/capability/",
            "/partnerships/all/",
            "/partnerships/agreements/inquiries/",
            "/partnerships/reports/achievement/",
            "/settings/regions/",
            "/settings/levels/",
            "/settings/sectors/",
            "/settings/entities/",
            "/access-control/",
            "/access-control/activity/",
            "/my-work/",
            "/market-needs/",
            "/service-providers/",
        ]
        for path in paths:
            with self.subTest(path=path):
                res = self.client.get(path, {"per_page": "10"})
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "makken-pagination.css")
                self.assertContains(res, "makken-pagination.js")

    def test_pagination_css_and_js_assets_are_valid(self):
        root = Path(settings.BASE_DIR)
        css = (root / "core/static/core/css/makken-pagination.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("justify-content: center", css)
        self.assertIn(".mk-pg-num.is-current", css)
        self.assertIn(".mk-pg-pill", css)
        js = (root / "core/static/core/js/makken-pagination.js").read_text(encoding="utf-8")
        self.assertIn("data-mk-per-page-select", js)
