"""Access helpers for assigned employees updating partnership clause progress."""
from django.db.models import Q


def is_assigned_partnership_employee(user, partnership_pk):
    if not user or not getattr(user, "is_authenticated", False) or not partnership_pk:
        return False
    from makken_mail.models import WorkAssignment
    return WorkAssignment.objects.filter(
        target_model="partnerships.partnership",
        target_key=partnership_pk,
    ).filter(Q(employee=user) | Q(assignees=user)).exists()
