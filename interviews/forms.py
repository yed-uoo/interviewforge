from django import forms
from resume_analyzer.models import Resume


class InterviewGeneratorForm(forms.Form):
    role = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'e.g. Backend Developer'
            }
        )
    )

    experience_level = forms.ChoiceField(
        choices=[
            ('fresher', 'Fresher'),
            ('junior', 'Junior'),
            ('mid', 'Mid-Level'),
            ('senior', 'Senior'),
        ],
        widget=forms.Select(
            attrs={
                'class': 'form-select form-select-lg'
            }
        )
    )

    job_description = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Paste job description here (optional)'
            }
        )
    )

    existing_resume = forms.ModelChoiceField(
        queryset=Resume.objects.none(),
        required=False,
        empty_label="Select previously analyzed resume",
        widget=forms.Select(
            attrs={
                'class': 'form-select'
            }
        )
    )

    resume_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.pdf'
            }
        )
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        if user:
            self.fields['existing_resume'].queryset = Resume.objects.filter(
                user=user
            ).order_by('-uploaded_at')