"""Public Arabic URL values map to existing, immutable development-state keys."""
from django import forms
from care_states.models import DevelopmentState


STATE_KEYS = {str(label): key for key, label in DevelopmentState.choices}


class DevelopmentFilterForm(forms.Form):
    development_state = forms.ChoiceField(
        required=False,
        label="حالة التطور",
        choices=[("", "جميع الحالات"), *((label, label) for label in STATE_KEYS)],
        error_messages={"invalid_choice": "اختر قدرة أو رغبة أو رعاية من قائمة حالات التطور."},
        widget=forms.Select(attrs={
            "id": "register-development-state",
            "data-development-filter": "",
            "aria-describedby": "development-filter-errors",
        }),
    )

    def __init__(self, *args, allowed_states=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_states is not None:
            allowed = set(allowed_states)
            self.fields["development_state"].choices = [
                ("", "جميع الحالات"),
                *((label, label) for label, key in STATE_KEYS.items() if key in allowed),
            ]


class DevelopmentFilter:
    def __init__(self, request, queryset, *, exact=False, allowed_states=None):
        self.form = DevelopmentFilterForm(request.GET, allowed_states=allowed_states)
        self.valid = self.form.is_valid()
        self.value = self.form.cleaned_data.get("development_state", "") if self.valid else ""
        self.params = {"development_state": self.value} if self.value else {}
        self.queryset = queryset
        if not self.valid:
            self.queryset = queryset.none()
        elif self.value:
            selected = STATE_KEYS[self.value]
            # The default willingness filter on /partnerships/ includes capable organizations;
            # exact=True filters strictly by the chosen state.
            states = [selected]
            if not exact and selected == DevelopmentState.WILLINGNESS:
                states.append(DevelopmentState.CAPABILITY)
            self.queryset = queryset.filter(development_state_id__in=states)
        self.context = {
            "development_filter_form": self.form,
            "development_filter_active": bool(self.value) or not self.valid,
        }
