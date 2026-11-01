from django import forms

from workflows.models import Workflow, WorkflowStep


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
        parameter_operations = {WorkflowStep.Operation.SCALE, WorkflowStep.Operation.OFFSET}
        if operation in parameter_operations and parameter is None:
            self.add_error("parameter", "This operation requires a parameter.")
        if operation not in parameter_operations and parameter is not None:
            self.add_error("parameter", "This operation does not use a parameter.")
        return cleaned
