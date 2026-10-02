from django.contrib.auth.models import User
from django.test import TestCase
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import AdminUserCreateForm, AdminUserEditForm, ForgotPasswordForm, ResetPasswordForm
from .models import Profile


class AdminUserFormTests(TestCase):
	def test_create_form_rejects_short_password(self):
		form = AdminUserCreateForm(data={
			'username': 'usuario1',
			'email': 'user@example.com',
			'password': '123',
			'role': 'ESTUDIANTE',
		})

		self.assertFalse(form.is_valid())
		self.assertIn('password', form.errors)

	def test_edit_form_accepts_optional_password(self):
		form = AdminUserEditForm(data={
			'email': 'new@example.com',
			'role': 'DOCENTE',
			'password': '',
		})

		self.assertTrue(form.is_valid())


class PasswordRecoveryFormTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='testuser', email='test@example.com', password='oldpass123')

	def test_forgot_password_form_valid(self):
		form = ForgotPasswordForm(data={'email': 'test@example.com'})
		self.assertTrue(form.is_valid())

	def test_forgot_password_form_rejects_nonexistent_email(self):
		form = ForgotPasswordForm(data={'email': 'nonexistent@example.com'})
		self.assertFalse(form.is_valid())
		self.assertIn('email', form.errors)

	def test_reset_password_form_valid(self):
		form = ResetPasswordForm(data={
			'password': 'newpass123456',
			'password_confirm': 'newpass123456',
		})
		self.assertTrue(form.is_valid())

	def test_reset_password_form_rejects_short_password(self):
		form = ResetPasswordForm(data={
			'password': '1234567',  # Only 7 chars
			'password_confirm': '1234567',
		})
		self.assertFalse(form.is_valid())
		self.assertIn('__all__', form.errors)

	def test_reset_password_form_rejects_mismatched_passwords(self):
		form = ResetPasswordForm(data={
			'password': 'newpass123456',
			'password_confirm': 'different123',
		})
		self.assertFalse(form.is_valid())
		self.assertIn('__all__', form.errors)


class PasswordRecoveryViewTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='testuser', email='test@example.com', password='oldpass123')
		Profile.objects.get_or_create(user=self.user, defaults={'role': 'ESTUDIANTE'})

	def test_forgot_password_get(self):
		response = self.client.get('/forgot-password/')
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'users/forgot_password.html')

	def test_forgot_password_post_valid(self):
		response = self.client.post('/forgot-password/', {'email': 'test@example.com'})
		self.assertEqual(response.status_code, 302)  # Redirect to login
		self.assertRedirects(response, '/login/')

	def test_forgot_password_post_nonexistent_email(self):
		response = self.client.post('/forgot-password/', {'email': 'nonexistent@example.com'})
		self.assertEqual(response.status_code, 200)
		# Check that the form is still displayed (not redirected)
		self.assertIn('form', response.context)
		form = response.context['form']
		self.assertFalse(form.is_valid())

	def test_reset_password_with_valid_token(self):
		token_generator = PasswordResetTokenGenerator()
		token = token_generator.make_token(self.user)
		uid = urlsafe_base64_encode(force_bytes(self.user.pk))
		
		response = self.client.get(f'/reset-password/{uid}/{token}/')
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'users/reset_password.html')

	def test_reset_password_post_valid(self):
		token_generator = PasswordResetTokenGenerator()
		token = token_generator.make_token(self.user)
		uid = urlsafe_base64_encode(force_bytes(self.user.pk))
		
		response = self.client.post(f'/reset-password/{uid}/{token}/', {
			'password': 'newpass123456',
			'password_confirm': 'newpass123456',
		})
		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, '/login/')
		
		# Verify password was changed
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password('newpass123456'))

	def test_reset_password_with_invalid_token(self):
		uid = urlsafe_base64_encode(force_bytes(self.user.pk))
		response = self.client.get(f'/reset-password/{uid}/invalid-token/')
		self.assertEqual(response.status_code, 302)
		self.assertRedirects(response, '/forgot-password/')
