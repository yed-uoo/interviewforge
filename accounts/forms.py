from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = [
            'username',
            'full_name',
            'email',
            'password1',
            'password2'
        ]