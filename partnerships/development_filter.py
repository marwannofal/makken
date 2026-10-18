"""Public Arabic URL values map to existing, immutable development-state keys."""
from django import forms
from care_states.models import DevelopmentState


STATE_KEYS = {str(label): key for key, label in DevelopmentState.choices}


class DevelopmentFilterForm(forms.Form):
    development_state = forms.ChoiceField(
        required=False,
        label="حالة التطور الحالي للجهة",
        choices=[("", "جميع الحالات"), *((label, label) for label in STATE_KEYS)],
        error_messages={"invalid_choice": "اختر قدرة أو رغبة أو رعاية من قائمة حالات التطور."},
        widget=forms.Select(attrs={
            "id": "register-development-state",
            "data-development-filter": "",
            "aria-describedby": "development-filter-errors",
        }),
    )


class DevelopmentFilter:
    def __init__(self, request, queryset):
        self.form = DevelopmentFilterForm(request.GET)
        self.valid = self.form.is_valid()
        self.value = self.form.cleaned_data.get("development_state", "") if self.valid else ""
        self.params = {"development_state": self.value} if self.value else {}
        self.queryset = queryset
        if not self.valid:
            self.queryset = queryset.none()
        elif self.value:
            selected = STATE_KEYS[self.value]
            # The willingness filter intentionally includes capable organizations.
            states = [selected]
            if selected == DevelopmentState.WILLINGNESS:
                states.append(DevelopmentState.CAPABILITY)
            self.queryset = queryset.filter(development_state_id__in=states)
        self.context = {
            "development_filter_form": self.form,
            "development_filter_active": bool(self.value) or not self.valid,
        }
