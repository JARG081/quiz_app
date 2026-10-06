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


class OwnProfileForm(forms.Form):
    alias = forms.CharField(label='Alias / Nombre Visible (oculta tu correo)', max_length=50, required=False)
    email = forms.EmailField(label='Correo electrónico', required=False)
    first_name = forms.CharField(label='Nombre', max_length=150, required=False)
    last_name = forms.CharField(label='Apellido', max_length=150, required=False)
    current_password = forms.CharField(label='Contraseña actual', required=False, widget=forms.PasswordInput)
    new_password = forms.CharField(label='Nueva contraseña', required=False, widget=forms.PasswordInput)
    new_password_confirm = forms.CharField(label='Confirmar nueva contraseña', required=False, widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        cleaned = super().clean()
        new_password = cleaned.get('new_password', '')
        confirmation = cleaned.get('new_password_confirm', '')
        current_password = cleaned.get('current_password', '')
        if new_password:
            if not current_password or not self.user or not self.user.check_password(current_password):
                self.add_error('current_password', 'La contraseña actual no es correcta.')
            if len(new_password) < 8:
                self.add_error('new_password', 'La nueva contraseña debe tener al menos 8 caracteres.')
            if new_password != confirmation:
                self.add_error('new_password_confirm', 'Las contraseñas no coinciden.')
        elif confirmation:
            self.add_error('new_password', 'Escribe una nueva contraseña.')
        return cleaned
