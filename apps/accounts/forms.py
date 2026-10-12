from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordMixin

from apps.core.forms import StyledFormMixin

from .models import User


class LoginForm(StyledFormMixin, AuthenticationForm):
    pass


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass


class UserCreateForm(StyledFormMixin, SetPasswordMixin, forms.ModelForm):
    password1, password2 = SetPasswordMixin.create_password_fields()

    class Meta:
        model = User
        fields = ["username", "display_name", "email", "role", "is_active"]

    def clean(self):
        self.validate_passwords()
        return super().clean()

    def _post_clean(self):
        super()._post_clean()
        self.validate_password_for_user(self.instance)

    def save(self, commit=True):
        user = super().save(commit=False)
        self.set_password_and_save(user, commit=commit)
        return user


class UserEditForm(StyledFormMixin, forms.ModelForm):
    new_password = forms.CharField(
        label="新しいパスワード",
        required=False,
        widget=forms.PasswordInput,
        help_text="変更する場合のみ入力してください。",
    )

    class Meta:
        model = User
        fields = ["display_name", "email", "role", "is_active"]

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user
