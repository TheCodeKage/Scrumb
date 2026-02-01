from django.forms import ModelForm, inlineformset_factory, Textarea, TextInput, NumberInput
from .models import *


class IdeaForm(ModelForm):
    class Meta:
        model = Idea
        exclude = ['author', 'added_on']

        widgets = {
            "idea": Textarea(attrs={'rows': 4, 'cols': 40}),
        }


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        exclude = ['author', 'source_idea', 'created_at', 'updated_at']
        widgets = {
            "title": TextInput(attrs={"placeholder": "Project title"}),
            "description": Textarea(attrs={"rows": 4}),
        }


class FeatureForm(ModelForm):
    class Meta:
        model = Feature
        fields = ["feature", "importance_score"]
        widgets = {
            "feature": Textarea(attrs={"rows": 2}),
            "importance_score": NumberInput(attrs={"min": 1, "max": 5}),
        }


FeatureFormSet = inlineformset_factory(
    Project,
    Feature,
    form=FeatureForm,
    extra=1,
    fields=["feature", "importance_score"],
    can_delete=True,
    widgets = {
        "feature": Textarea(attrs={
            "rows": 2,
            "class": "form-control"
        }),
        "importance_score": NumberInput(attrs={
            "class": "form-control",
            "min": 1,
            "max": 5
        }),
    }
)
