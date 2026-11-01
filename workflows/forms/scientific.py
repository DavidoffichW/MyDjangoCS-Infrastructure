from django import forms

from services.scientific.investigations import default_investigation


class ScientificInvestigationForm(forms.Form):
    SENSOR_CHOICES = [
        ("sensor_alpha", "Sensor Alpha"),
        ("sensor_bravo", "Sensor Bravo"),
        ("sensor_charlie", "Sensor Charlie"),
        ("sensor_delta", "Sensor Delta"),
    ]
    METHOD_CHOICES = [
        ("time-window-mean/1", "Time-window mean"),
        ("graph-neighborhood-mean/1", "One-hop graph mean"),
    ]
    target_sensors = forms.MultipleChoiceField(
        choices=SENSOR_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        initial=["sensor_alpha", "sensor_bravo"],
    )
    method = forms.ChoiceField(choices=METHOD_CHOICES)
    missing_policy = forms.ChoiceField(
        choices=[("exclude", "Exclude explicit missing values"), ("propagate", "Propagate missing")]
    )
    start = forms.CharField(initial="2026-01-01T00:00:00Z")
    end = forms.CharField(initial="2026-01-01T03:00:00Z")
    max_records = forms.IntegerField(min_value=1, max_value=5000, initial=100)
    max_targets = forms.IntegerField(min_value=1, max_value=100, initial=4)
    idempotency_key = forms.CharField(max_length=100)

    def clean(self) -> dict:
        cleaned = super().clean()
        if (
            cleaned.get("method") == "graph-neighborhood-mean/1"
            and len(cleaned.get("target_sensors", [])) != 1
        ):
            self.add_error("target_sensors", "The one-hop method requires exactly one target.")
        return cleaned

    def declaration(self, research_run) -> dict:
        declaration = default_investigation(research_run)
        declaration.update(
            {
                "method": self.cleaned_data["method"],
                "method_parameters": {"max_hops": 1}
                if self.cleaned_data["method"] == "graph-neighborhood-mean/1"
                else {},
                "missing_policy": self.cleaned_data["missing_policy"],
                "resource_budget": {
                    "max_records": self.cleaned_data["max_records"],
                    "max_targets": self.cleaned_data["max_targets"],
                },
                "target_sensors": self.cleaned_data["target_sensors"],
                "temporal_scope": {
                    "end": self.cleaned_data["end"],
                    "start": self.cleaned_data["start"],
                },
            }
        )
        return declaration
