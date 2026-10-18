"""Market needs, confirmed contributions and append-only application history."""
import uuid
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from partnerships.attachment_storage import willingness_storage, delete_private_files


class NeedStatus(models.TextChoices):
    NEW = "new", "جديد"
    WORKING = "working", "جاري العمل"
    COMPLETE = "complete", "مكتملة الدعم"
    REJECTED = "rejected", "تم الرفض"


class SponsorshipStatus(models.TextChoices):
    NEW = "new", "جديد"
    APPROVED = "approved", "اعتماد"
    REJECTED = "rejected", "رفض"


class Need(models.Model):
    title = models.CharField("حاجة السوق", max_length=200)
    sector = models.ForeignKey("sectors.Sector", on_delete=models.PROTECT)
    specialization = models.ForeignKey("specializations.Specialization", on_delete=models.PROTECT)
    regions = models.ManyToManyField("regions.Region", related_name="market_needs", through="NeedRegion")
    description = models.TextField("وصف الحاجة", max_length=4000)
    duration = models.PositiveIntegerField("المدة الزمنية")
    duration_unit = models.CharField(max_length=8, choices=[("day", "يوم"), ("month", "شهر"), ("year", "سنة")])
    source = models.CharField("مصدر الحاجة", max_length=300)
    beneficiaries = models.PositiveIntegerField("عدد المستفيدين")
    program = models.ForeignKey("training_programs.TrainingProgram", on_delete=models.PROTECT)
    program_name = models.CharField(max_length=200, editable=False)
    program_category = models.CharField(max_length=100, editable=False)
    training_type = models.CharField(max_length=16, editable=False)
    total_cost = models.DecimalField(max_digits=14, decimal_places=2, editable=False)
    requested_support = models.DecimalField("قيمة الدعم المطلوبة", max_digits=14, decimal_places=2)
    approved_support = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    observed_on = models.DateField("تاريخ الرصد", default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=NeedStatus.choices, default=NeedStatus.NEW, editable=False, db_index=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_market_needs")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(total_cost__gt=0), name="market_need_cost_positive"),
            models.CheckConstraint(condition=models.Q(requested_support__gt=0, requested_support__lte=models.F("total_cost")), name="market_need_requested_valid"),
            models.CheckConstraint(condition=models.Q(approved_support__gte=0, approved_support__lte=models.F("total_cost")), name="market_need_funding_limit"),
            models.CheckConstraint(condition=models.Q(beneficiaries__gt=0, duration__gt=0), name="market_need_counts_positive"),
            models.CheckConstraint(condition=models.Q(status__in=NeedStatus.values), name="market_need_status_enum"),
            models.CheckConstraint(condition=models.Q(duration_unit__in=["day", "month", "year"]), name="market_need_duration_enum"),
        ]

    @property
    def number(self):
        return f"MKT-{self.pk:06d}"

    @property
    def remaining(self):
        return self.total_cost - self.approved_support

    @property
    def funding_percent(self):
        return percentage(self.approved_support, self.total_cost)

    @property
    def seat_cost(self):
        return (self.total_cost / self.beneficiaries).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

    @property
    def arrangement(self):
        count = getattr(self, "approved_count", None)
        if count is None:
            count = self.sponsorships.filter(status=SponsorshipStatus.APPROVED).count()
        if count > 1:
            return "تحالف"
        if count == 1:
            return "فردي" if self.approved_support == self.total_cost else "مساهمة واحدة جزئية"
        return "لم يُعتمد دعم بعد"

    def __str__(self):
        return self.title


def percentage(value, total):
    return (Decimal(value) * 100 / Decimal(total)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP) if total else Decimal("0.00")


class NeedRegion(models.Model):
    need = models.ForeignKey(Need, on_delete=models.CASCADE)
    region = models.ForeignKey("regions.Region", on_delete=models.PROTECT)

    class Meta:
        db_table = "market_needs_need_regions"
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["need", "region"], name="market_need_region_unique")]


class ExpenseLine(models.Model):
    need = models.ForeignKey(Need, on_delete=models.CASCADE, related_name="expense_lines")
    expense_item = models.ForeignKey("expense_items.ExpenseItem", on_delete=models.PROTECT)
    sponsorship_shape = models.ForeignKey("sponsorship_shapes.SponsorshipShape", on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "pk"]
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["need", "expense_item"], name="market_need_expense_unique"), models.CheckConstraint(condition=models.Q(amount__gt=0), name="market_line_amount_positive")]

    @property
    def share(self):
        return percentage(self.amount, self.need.total_cost)


class Sponsorship(models.Model):
    need = models.ForeignKey(Need, on_delete=models.CASCADE, related_name="sponsorships")
    partnership = models.ForeignKey("partnerships.Partnership", on_delete=models.PROTECT, related_name="market_sponsorships")
    status = models.CharField(max_length=12, choices=SponsorshipStatus.choices, default=SponsorshipStatus.NEW)
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(max_length=4000, blank=True)
    rejection_reason = models.TextField(max_length=2000, blank=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, editable=False)
    level = models.ForeignKey("levels.Level", null=True, on_delete=models.PROTECT, editable=False)
    level_name = models.CharField(max_length=100, blank=True, editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, editable=False, related_name="updated_market_sponsorships")
    updated_at = models.DateTimeField(default=timezone.now, null=True, editable=False)

    class Meta:
        ordering = ["pk"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["need", "partnership"], name="market_need_sponsor_unique"),
            models.CheckConstraint(condition=(models.Q(status="approved", amount__gt=0) | models.Q(status__in=["new", "rejected"], amount=0)), name="market_sponsor_amount_status"),
            models.CheckConstraint(condition=~models.Q(status="rejected", rejection_reason=""), name="market_sponsor_rejection_reason"),
        ]

    @property
    def percent(self):
        return percentage(self.amount, self.need.total_cost)

    @property
    def allocated_amount(self):
        return sum((item.amount for item in self.allocations.all()), Decimal("0.00"))

    @property
    def unallocated_amount(self):
        return self.amount - self.allocated_amount if self.status == SponsorshipStatus.APPROVED else Decimal("0.00")


class SponsorshipAllocation(models.Model):
    sponsorship = models.ForeignKey(Sponsorship, on_delete=models.CASCADE, related_name="allocations")
    expense_line = models.ForeignKey(ExpenseLine, on_delete=models.PROTECT, related_name="funding_allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        default_permissions = ()
        ordering = ["expense_line__position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["sponsorship", "expense_line"], name="market_sponsor_line_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="market_allocation_positive"),
        ]


class AuditEvent(models.Model):
    need = models.ForeignKey(Need, null=True, on_delete=models.SET_NULL, related_name="events")
    need_number = models.CharField(max_length=30)
    sponsorship = models.ForeignKey(Sponsorship, null=True, on_delete=models.SET_NULL)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()


def support_path(instance, filename):
    return "market-support/" + uuid.uuid4().hex + Path(filename).suffix.lower()


class SupportAttachment(models.Model):
    sponsorship = models.ForeignKey(Sponsorship, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(storage=willingness_storage, upload_to=support_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=40)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        default_permissions = ()


@receiver(post_delete, sender=SupportAttachment)
def clean_support_file(sender, instance, **kwargs):
    if instance.file.name:
        name = instance.file.name
        transaction.on_commit(lambda: delete_private_files([name]))
