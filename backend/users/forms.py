from django import forms
from django.contrib.auth.models import User

from .models import Profile


class AdminUserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if len(username) < 3:
            raise forms.ValidationError('El nombre de usuario debe tener al menos 3 caracteres.')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya existe.')
        return username

    def clean_password(self):
        password = self.cleaned_data['password']
        if len(password) < 8:
            raise forms.ValidationError('La contraseña debe tener al menos 8 caracteres.')
        return password


class AdminUserEditForm(forms.Form):
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES)
    password = forms.CharField(required=False, widget=forms.PasswordInput)

    def clean_password(self):
        password = self.cleaned_data.get('password', '').strip()
        if password and len(password) < 8:
            raise forms.ValidationError('La nueva contraseña debe tener al menos 8 caracteres.')
        return password


class ForgotPasswordForm(forms.Form):
    """Formulario para solicitar recuperación de contraseña."""
    email = forms.EmailField(label='Correo electrónico')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if not User.objects.filter(email=email).exists():
            raise forms.ValidationError('No hay cuenta asociada con este correo.')
        return email


class ResetPasswordForm(forms.Form):
    """Formulario para restablecer contraseña con confirmación."""
    password = forms.CharField(label='Nueva contraseña', widget=forms.PasswordInput)
    password_confirm = forms.CharField(label='Confirmar contraseña', widget=forms.PasswordInput)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password', '').strip()
        password_confirm = cleaned_data.get('password_confirm', '').strip()

        if password and len(password) < 8:
            raise forms.ValidationError('La contraseña debe tener al menos 8 caracteres.')
        
        if password != password_confirm:
            raise forms.ValidationError('Las contraseñas no coinciden.')
        
        return cleaned_data
