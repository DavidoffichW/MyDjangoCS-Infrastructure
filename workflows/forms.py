from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import forms

from .models import Workflow, WorkflowStep
from .scientific_services import default_investigation
from .services import MAX_ABS_INPUT_VALUE, MAX_INPUT_DECIMAL_PLACES, MAX_INPUT_VALUES


def parse_input_values(raw: str) -> list[Decimal]:
    parts = [part.strip() for part in raw.replace("\n", ",").split(",")]
    parts = [part for part in parts if part]
    if not parts:
        raise forms.ValidationError("Enter at least one numerical value.")
    if len(parts) > MAX_INPUT_VALUES:
        raise forms.ValidationError(f"At most {MAX_INPUT_VALUES} values are allowed.")

    values: list[Decimal] = []
    for part in parts:
        try:
            value = Decimal(part)
        except InvalidOperation as exc:
            raise forms.ValidationError(f"{part!r} is not a decimal number.") from exc
        if not value.is_finite():
            raise forms.ValidationError("NaN and infinite values are not allowed.")
        if abs(value) > MAX_ABS_INPUT_VALUE:
            raise forms.ValidationError(
                f"Values must be between {-MAX_ABS_INPUT_VALUE} and {MAX_ABS_INPUT_VALUE}."
            )
        if value.as_tuple().exponent < -MAX_INPUT_DECIMAL_PLACES:
            raise forms.ValidationError(
                f"Values may use at most {MAX_INPUT_DECIMAL_PLACES} decimal places."
            )
        values.append(value)
    return values


class WorkflowForm(forms.ModelForm):
    class Meta:
        model = Workflow
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Pressure sample checks"})}


class StepForm(forms.ModelForm):
    class Meta:
        model = WorkflowStep
        fields = ["operation", "parameter"]

    def clean(self) -> dict:
        cleaned = super().clean()
        operation = cleaned.get("operation")
        parameter = cleaned.get("parameter")
        parameter_operations = {
            WorkflowStep.Operation.SCALE,
            WorkflowStep.Operation.OFFSET,
        }
        if operation in parameter_operations and parameter is None:
            self.add_error("parameter", "This operation requires a parameter.")
        if operation not in parameter_operations and parameter is not None:
            self.add_error("parameter", "This operation does not use a parameter.")
        return cleaned


class AdmissionForm(forms.Form):
    input_values = forms.CharField(
        max_length=2048,
        initial="2, 4, 6",
        help_text="Comma-separated decimals; up to 100 values.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.CharField(
        max_length=100,
        help_text="Repeating the same key and input returns the existing job.",
    )

    def clean_input_values(self) -> list[Decimal]:
        return parse_input_values(self.cleaned_data["input_values"])


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
        if cleaned.get("method") == "graph-neighborhood-mean/1" and len(
            cleaned.get("target_sensors", [])
        ) != 1:
            self.add_error("target_sensors", "The one-hop method requires exactly one target.")
        return cleaned

    def declaration(self, research_run) -> dict:
        declaration = default_investigation(research_run)
        declaration.update(
            {
                "method": self.cleaned_data["method"],
                "method_parameters": (
                    {"max_hops": 1}
                    if self.cleaned_data["method"] == "graph-neighborhood-mean/1"
                    else {}
                ),
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
