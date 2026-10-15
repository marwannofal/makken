from django import forms

from .models import DevelopmentState


class ColorChangeForm(forms.Form):
    state = forms.ChoiceField(choices=DevelopmentState.choices)
    color = forms.RegexField(
        regex=r"\A#[0-9A-Fa-f]{6}\Z", max_length=7, min_length=7,
        error_messages={"invalid": "أدخل لونًا صحيحًا مثل #24B3AF.", "required": "اختر اللون الجديد."},
    )
    snapshot = forms.CharField(max_length=2048)

    def clean_color(self):
        return self.cleaned_data["color"].upper()
