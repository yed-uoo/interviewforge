from django import forms
from mcq_engine.models import Topic, MCQTest


class AssessmentConfigForm(forms.Form):
    topic = forms.ModelChoiceField(
        queryset=Topic.objects.all(),
        empty_label="Select a Topic",
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        error_messages={'required': 'Please select a topic to start the test.'}
    )
    experience_level = forms.ChoiceField(
        choices=MCQTest.ExperienceLevel.choices,
        initial=MCQTest.ExperienceLevel.FRESHER,
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        error_messages={'required': 'Please select your experience level.'}
    )
    question_count = forms.TypedChoiceField(
        choices=[(5, '5 Questions'), (10, '10 Questions'), (15, '15 Questions'), (20, '20 Questions')],
        coerce=int,
        initial=10,
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'}),
        error_messages={'required': 'Please select the number of questions.'}
    )
