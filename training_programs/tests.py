import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from expense_items.models import ExpenseItem
from .models import ProgramExpenseItem, TrainingProgram
from .views import TOKEN_AGE


class TrainingProgramsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("programs-test", password="test-only-password")
        self.client.force_login(self.user)
        self.url = reverse("training_programs:index")
        self.ids = list(ExpenseItem.objects.values_list("pk", flat=True))
        self.category = "intermediate_diploma"

    def row(self, item):
        return next(row for row in self.client.get(self.url).context["rows"] if row["id"] == item.pk)

    def preview(self, operation="add", item=None, name="برنامج تجريبي", category=None, expenses=None, types=None, active="1"):
        snapshot = self.client.get(self.url).context["add_snapshot"] if operation == "add" else self.client.get(self.url, {"edit": item.pk}).context["editor_form"].initial["snapshot"] if operation == "edit" else self.row(item)[f"{operation}_snapshot"]
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot, "name": name,
                                          "category": self.category if category is None else category,
                                          "expense_items": self.ids[:2] if expenses is None else expenses,
                                          "training_types": ["training"] if types is None else types, "is_active": active})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def create(self, **kwargs):
        response = self.preview(**kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.confirm(response).status_code, 302)
        return TrainingProgram.objects.latest("pk")

    def choices(self, item=None):
        response = self.client.get(self.url, {"edit": item.pk if item else "new"})
        return set(response.context["editor_form"].fields["expense_items"].queryset.values_list("pk", flat=True))

    def test_empty_state_headers_and_sidebar_links(self):
        response = self.client.get(self.url)
        self.assertContains(response, "لا توجد برامج تدريب بعد")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertNotContains(response, "لوحة الإدارة")
        for url in ["/", "/settings/expense-items/", "/settings/sectors/", self.url]:
            page = self.client.get(url)
            self.assertContains(page, 'href="/settings/training-programs/"')
            self.assertContains(page, 'href="/settings/expense-items/"')
            self.assertContains(page, 'href="/settings/sectors/"')

    def test_anonymous_get_post_require_login(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(TrainingProgram.objects.count(), 0)

    def test_form_order_and_fixed_single_category_choices(self):
        response = self.client.get(self.url, {"edit": "new"})
        html = response.content.decode()
        positions = [html.index(marker) for marker in ['id="program-name"', 'id="program-category"', 'id="program-expense-items"', 'name="training_types"', 'name="is_active"']]
        self.assertEqual(positions, sorted(positions))
        field = response.context["editor_form"].fields["category"]
        self.assertEqual(list(field.choices), [("", "اختر تصنيف البرنامج"), ("intermediate_diploma", "الدبلوم التدريبي (المتوسط)"), ("associate_diploma", "الدبلوم التدريبي (المشارك)"), ("qualifying_program", "البرنامج التأهيلي"), ("qualifying_course", "الدورة التأهيلية"), ("development_course", "الدورة التطويرية")])
        self.assertFalse(field.widget.allow_multiple_selected)
        self.assertEqual(response.context["editor_form"].fields["training_types"].widget.input_type, "radio")

    def test_add_multi_expenses_requires_confirm_cancel_does_not_write(self):
        response = self.preview(types=["operational"], active="0")
        self.assertContains(response, "تأكيد إضافة البرنامج")
        self.assertEqual(TrainingProgram.objects.count(), 0)
        self.client.get(self.url)
        self.assertEqual(ProgramExpenseItem.objects.count(), 0)
        self.assertEqual(self.confirm(response).status_code, 302)
        item = TrainingProgram.objects.get()
        self.assertEqual((item.category, item.is_training, item.is_operational, item.is_active), (self.category, False, True, False))
        self.assertEqual(set(item.expense_items.values_list("pk", flat=True)), set(self.ids[:2]))
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_expenses_reusable_across_programs_and_never_hidden(self):
        one = self.create(name="برنامج أول")
        two = self.create(name="برنامج ثان", expenses=self.ids[1:3])
        shared = ExpenseItem.objects.get(pk=self.ids[1])
        self.assertEqual(set(shared.training_programs.values_list("pk", flat=True)), {one.pk, two.pk})
        for item in [None, one, two]:
            self.assertEqual(self.choices(item), set(self.ids))
        form = self.client.get(self.url, {"edit": one.pk}).context["editor_form"]
        self.assertEqual(set(form.initial["expense_items"]), set(self.ids[:2]))

    def test_two_pending_programs_can_use_same_expense_and_versions_remain_unchanged(self):
        before = dict(ExpenseItem.objects.values_list("pk", "version"))
        one = self.preview(name="برنامج أول")
        two = self.preview(name="برنامج ثان")
        self.assertEqual(self.confirm(one).status_code, 302)
        self.assertEqual(self.confirm(two).status_code, 302)
        self.assertEqual(ProgramExpenseItem.objects.count(), 4)
        self.assertEqual(dict(ExpenseItem.objects.values_list("pk", "version")), before)

    def test_edit_changes_every_field_only_after_confirm(self):
        item = self.create()
        response = self.preview("edit", item, name="برنامج محدث", category="development_course", expenses=self.ids[1:3], types=["operational"], active="0")
        self.assertContains(response, "الدورة التطويرية")
        item.refresh_from_db()
        self.assertEqual(item.name, "برنامج تجريبي")
        self.assertEqual(self.confirm(response).status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.name, item.category, item.is_training, item.is_operational, item.is_active, item.version), ("برنامج محدث", "development_course", False, True, False, 2))
        self.assertEqual(set(item.expense_items.values_list("pk", flat=True)), set(self.ids[1:3]))

    def test_unlinking_and_deleting_program_do_not_change_other_program_or_expenses(self):
        one = self.create(name="برنامج أول")
        two = self.create(name="برنامج ثان")
        self.assertEqual(self.confirm(self.preview("edit", one, name=one.name, expenses=self.ids[1:2])).status_code, 302)
        self.assertEqual(set(two.expense_items.values_list("pk", flat=True)), set(self.ids[:2]))
        response = self.preview("delete", one)
        self.client.get(self.url, {"action": "delete", "id": one.pk})
        self.assertTrue(TrainingProgram.objects.filter(pk=one.pk).exists())
        self.assertEqual(self.confirm(response).status_code, 302)
        self.assertEqual(set(two.expense_items.values_list("pk", flat=True)), set(self.ids[:2]))
        self.assertEqual(ExpenseItem.objects.count(), len(self.ids))
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_toggle_preserves_category_types_expenses_and_expense_statuses(self):
        item = self.create(types=["operational"])
        before = dict(ExpenseItem.objects.values_list("pk", "is_active"))
        response = self.preview("toggle", item)
        item.refresh_from_db()
        self.assertTrue(item.is_active)
        self.assertEqual(self.confirm(response).status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertEqual(item.training_types, ["operational"])
        self.assertEqual(set(item.expense_items.values_list("pk", flat=True)), set(self.ids[:2]))
        self.assertEqual(dict(ExpenseItem.objects.values_list("pk", "is_active")), before)
        self.assertEqual(self.confirm(self.preview("toggle", item)).status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_each_training_type_is_valid(self):
        for i, types in enumerate([["training"], ["operational"]]):
            item = self.create(name=f"نوع {i}", types=types)
            self.assertEqual(item.training_types, types)

    def test_missing_invalid_categories_types_expenses_and_status_rejected(self):
        for category in ["", "unknown", "training,operational"]:
            self.assertEqual(self.preview(category=category).status_code, 400)
        for types in [[], ["unknown"], ["training", "unknown"], ["training", "operational"], ["operational", "training"]]:
            self.assertEqual(self.preview(types=types).status_code, 400)
        for expenses in [[], ["not-id"], [99999999], [self.ids[0], 99999999]]:
            self.assertEqual(self.preview(expenses=expenses).status_code, 400)
        self.assertEqual(self.preview(active="invalid").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)
        self.assertEqual(TrainingProgram.objects.count(), 0)

    def test_invalid_names_duplicates_and_normalization(self):
        for name in ["", "  ", "a" * 201, "<script>x</script>", "bad\x00name", "bad\u202ename", "＜script＞"]:
            self.assertEqual(self.preview(name=name).status_code, 400)
        item = self.create(name="  Test   Program  ")
        self.assertEqual(item.name, "Test Program")
        self.assertEqual(self.preview(name="test program").status_code, 400)
        other = self.create(name="برنامج آخر")
        self.assertEqual(self.preview("edit", other, name="Test Program").status_code, 400)

    def test_no_change_and_invalid_editor_ids(self):
        item = self.create()
        response = self.preview("edit", item, name=item.name)
        self.assertIn("notice", response.context)
        self.assertNotIn("pending", response.context)
        for value in ["0", "not-id", "9" * 30]:
            self.assertEqual(self.client.get(self.url, {"edit": value}).status_code, 404)

    def test_inactive_expense_remains_selectable_and_labelled(self):
        expense = ExpenseItem.objects.first()
        expense.is_active = False
        expense.save()
        self.assertContains(self.client.get(self.url, {"edit": "new"}), expense.name + " (غير نشط)")
        self.assertIn(expense, self.create(expenses=[expense.pk]).expense_items.all())

    def test_expense_protected_while_linked_and_deletable_after_last_program_removed(self):
        item = self.create(expenses=self.ids[:1])
        expense = ExpenseItem.objects.get(pk=self.ids[0])
        with self.assertRaises(ProtectedError):
            expense.delete()
        url = reverse("expense_items:index")
        row = next(row for row in self.client.get(url).context["rows"] if row["id"] == expense.pk)
        response = self.client.post(url, {"action": "preview", "snapshot": row["delete_snapshot"]})
        result = self.client.post(url, {"action": "confirm", "token": response.context["pending"]["token"]})
        self.assertEqual(result.status_code, 409)
        self.assertTrue(ExpenseItem.objects.filter(pk=expense.pk).exists())
        self.assertEqual(self.confirm(self.preview("delete", item)).status_code, 302)
        expense.delete()
        self.assertFalse(ExpenseItem.objects.filter(pk=expense.pk).exists())

    def test_database_enforces_category_types_and_unique_link(self):
        item = self.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingProgram.objects.create(name="تصنيف خاطئ", category="invalid")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingProgram.objects.create(name="دون نوع", category=self.category, is_training=False, is_operational=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingProgram.objects.create(name="نوعان معًا", category=self.category, is_training=True, is_operational=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProgramExpenseItem.objects.create(program=item, expense_item_id=self.ids[0])

    def test_stale_program_snapshot_and_confirmation(self):
        item = self.create()
        snapshot = self.client.get(self.url, {"edit": item.pk}).context["editor_form"].initial["snapshot"]
        responses = [self.preview(op, item, name="برنامج محدث") for op in ["edit", "toggle", "delete"]]
        item.version += 1
        item.save()
        for response in responses:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": snapshot}).status_code, 409)

    def test_changed_linked_expense_invalidates_program_confirmations(self):
        item = self.create()
        responses = [self.preview(op, item, name="اسم جديد") for op in ["edit", "toggle", "delete"]]
        expense = item.expense_items.first()
        expense.name = "بند محدث"
        expense.version += 1
        expense.save()
        for response in responses:
            self.assertEqual(self.confirm(response).status_code, 409)

    def test_changed_or_deleted_new_expense_rejects_without_partial_update(self):
        item = self.create(expenses=self.ids[:1])
        for mode, pk in zip(["rename", "delete"], self.ids[2:4]):
            response = self.preview("edit", item, name="اسم غير محفوظ", expenses=[pk], category="qualifying_course", types=["operational"])
            expense = ExpenseItem.objects.get(pk=pk)
            if mode == "rename":
                expense.name = "بند تغير بعد المراجعة"
                expense.version += 1
                expense.save()
            else:
                expense.delete()
            self.assertEqual(self.confirm(response).status_code, 409)
            item.refresh_from_db()
            self.assertEqual((item.name, item.category, item.training_types), ("برنامج تجريبي", self.category, ["training"]))
            self.assertEqual(list(item.expense_items.values_list("pk", flat=True)), self.ids[:1])

    def test_other_program_links_do_not_invalidate_confirmation(self):
        one = self.create(name="برنامج أول")
        response = self.preview("edit", one, name="برنامج أول محدث")
        self.create(name="برنامج ثان")
        self.assertEqual(self.confirm(response).status_code, 302)

    def test_link_change_rejects_stale_confirmation_even_without_version_change(self):
        item = self.create()
        response = self.preview("edit", item, name="اسم غير محفوظ")
        item.expense_items.remove(self.ids[0])
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_confirmation_tampering_expiry_other_user_and_operation(self):
        response = self.preview()
        token = response.context["pending"]["token"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token + "bad"}).status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + TOKEN_AGE + 10):
            self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        snapshot = self.client.get(self.url).context["add_snapshot"]
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": snapshot}).status_code, 400)
        self.client.force_login(get_user_model().objects.create_user("other-program-user"))
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(TrainingProgram.objects.count(), 0)

    def test_csrf_preview_and_confirm(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        snapshot = client.get(self.url).context["add_snapshot"]
        data = {"action": "preview", "operation": "add", "snapshot": snapshot, "name": "برنامج آمن", "category": self.category,
                "expense_items": self.ids[:1], "training_types": ["training"], "is_active": "1"}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        data = {"action": "confirm", "token": response.context["pending"]["token"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertEqual(client.post(self.url, {**data, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_pagination_and_escaping(self):
        for i in range(16):
            TrainingProgram.objects.create(name=f"Program {i}", category=self.category)
        self.assertEqual(len(self.client.get(self.url).context["rows"]), 15)
        self.assertEqual(len(self.client.get(self.url, {"page": 2}).context["rows"]), 1)
        TrainingProgram.objects.all().delete()
        TrainingProgram.objects.create(name='<script>alert("x")</script>', category=self.category)
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")

    def test_table_has_all_six_columns_with_values_under_matching_headers(self):
        from html.parser import HTMLParser

        item = self.create(types=["operational"])

        class RowParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_row, self.cell, self.cells = False, None, []

            def handle_starttag(self, tag, attrs):
                if tag == "tr" and dict(attrs).get("data-program-row") == str(item.pk):
                    self.in_row = True
                elif self.in_row and tag in {"th", "td"}:
                    self.cell = []

            def handle_data(self, data):
                if self.cell is not None:
                    self.cell.append(data)

            def handle_endtag(self, tag):
                if self.in_row and tag in {"th", "td"} and self.cell is not None:
                    self.cells.append(" ".join("".join(self.cell).split()))
                    self.cell = None
                elif tag == "tr":
                    self.in_row = False

        parser = RowParser()
        parser.feed(self.client.get(self.url).content.decode())
        self.assertEqual(len(parser.cells), 6)
        self.assertEqual(parser.cells[0], item.name)
        self.assertEqual(parser.cells[1], "الدبلوم التدريبي (المتوسط)")
        for expense in item.expense_items.all():
            self.assertIn(expense.name, parser.cells[2])
        self.assertNotIn("تدريبي", parser.cells[3])
        self.assertIn("تشغيلي", parser.cells[3])
        self.assertEqual(parser.cells[4], "نشط")
        self.assertIn("تعديل", parser.cells[5])
        self.assertIn("حذف", parser.cells[5])

    def test_single_type_radio_and_forged_double_choice_rejected(self):
        from .forms import TrainingProgramForm
        from .views import CONFIRM_SALT, _sign
        from django.core.exceptions import ValidationError

        form = TrainingProgramForm(initial={"training_types": "training"})
        self.assertEqual(form.fields["training_types"].widget.input_type, "radio")
        for types in [["training", "operational"], ["operational", "training"], ["training", "training"]]:
            self.assertEqual(self.preview(types=types).status_code, 400)
        pending = self.preview().context["pending"]
        payload = {key: pending[key] for key in ["operation", "id", "version", "links", "selected", "selected_state", "name", "category", "is_active"]}
        payload["training_types"] = ["training", "operational"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": _sign(payload, self.user, CONFIRM_SALT)}).status_code, 400)
        invalid = TrainingProgram(name="نوعان", category=self.category, is_training=True, is_operational=True)
        with self.assertRaises(ValidationError):
            invalid.clean()
        self.assertEqual(TrainingProgram.objects.count(), 0)
