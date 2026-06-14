from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label=_("Email"), required=True)
    website = forms.CharField(required=False, widget=forms.HiddenInput)
    remember_me = forms.BooleanField(label=_("Remember me"), required=False)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_website(self):
        value = self.cleaned_data.get("website")
        if value:
            raise forms.ValidationError(_("Registration could not be completed."))
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.is_active = False
        if commit:
            user.save()
        return user

