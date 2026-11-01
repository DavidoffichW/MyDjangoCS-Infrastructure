from decimal import Decimal, InvalidOperation

from django import forms

from services.workflows.contracts import (
    MAX_ABS_INPUT_VALUE,
    MAX_INPUT_DECIMAL_PLACES,
    MAX_INPUT_VALUES,
)


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


class AdmissionForm(forms.Form):
    input_values = forms.CharField(
        max_length=2048,
        initial="2, 4, 6",
        help_text="Comma-separated decimals; up to 100 values.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    idempotency_key = forms.CharField(
        max_length=100, help_text="Repeating the same key and input returns the existing job."
    )

    def clean_input_values(self) -> list[Decimal]:
        return parse_input_values(self.cleaned_data["input_values"])
