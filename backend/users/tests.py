from django.contrib.auth.models import User
from django.test import TestCase
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .forms import AdminUserCreateForm, AdminUserEditForm, ForgotPasswordForm, OwnProfileForm, ResetPasswordForm
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

	def test_forgot_password_form_accepts_nonexistent_email(self):
		form = ForgotPasswordForm(data={'email': 'nonexistent@example.com'})
		self.assertTrue(form.is_valid())

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
		response = self.client.post('/forgot-password/', {'email': 'nonexistent@example.com'}, follow=True)
		self.assertContains(response, 'Si el correo existe, recibirás un enlace.')

	def test_forgot_password_handles_duplicate_emails_case_insensitively(self):
		User.objects.create_user(username='duplicate', email='TEST@example.com', password='oldpass123')
		response = self.client.post('/forgot-password/', {'email': 'test@example.com'}, follow=True)
		self.assertContains(response, 'Si el correo existe, recibirás un enlace.')

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


class OwnProfileTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='profile_user', email='old@example.com', password='oldpass123',
			first_name='Old', last_name='Name',
		)
		Profile.objects.filter(user=self.user).update(role='ESTUDIANTE')
		self.client.force_login(self.user)

	def test_profile_get_is_available_to_authenticated_user(self):
		response = self.client.get('/profile/')
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'users/profile.html')

	def test_profile_updates_personal_data(self):
		response = self.client.post('/profile/', {
			'email': 'new@example.com', 'first_name': 'New', 'last_name': 'Person',
			'current_password': '', 'new_password': '', 'new_password_confirm': '',
		})
		self.assertRedirects(response, '/profile/')
		self.user.refresh_from_db()
		self.assertEqual(self.user.email, 'new@example.com')
		self.assertEqual(self.user.first_name, 'New')
		self.assertEqual(self.user.last_name, 'Person')

	def test_profile_rejects_wrong_current_password(self):
		form = OwnProfileForm(data={
			'email': self.user.email, 'first_name': '', 'last_name': '',
			'current_password': 'wrongpass', 'new_password': 'newpass123',
			'new_password_confirm': 'newpass123',
		}, user=self.user)
		self.assertFalse(form.is_valid())
		self.assertIn('current_password', form.errors)

	def test_profile_changes_password_with_current_password(self):
		response = self.client.post('/profile/', {
			'email': self.user.email, 'first_name': '', 'last_name': '',
			'current_password': 'oldpass123', 'new_password': 'newpass123',
			'new_password_confirm': 'newpass123',
		})
		self.assertRedirects(response, '/profile/')
		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password('newpass123'))


class BulkUserImportTests(TestCase):
	def setUp(self):
		self.admin = User.objects.create_user(username='admin_bulk', password='password123')
		Profile.objects.filter(user=self.admin).update(role='ADMIN')
		self.client.force_login(self.admin)

	def test_bulk_import_csv(self):
		csv_text = "estudiante1@test.com, Juan, Pérez, ESTUDIANTE\ndocente1@test.com, María, Gomez, DOCENTE"
		response = self.client.post('/admin/users/bulk-import/', {
			'raw_text': csv_text,
			'default_role': 'ESTUDIANTE',
		})
		self.assertRedirects(response, '/admin/dashboard/')
		self.assertTrue(User.objects.filter(email='estudiante1@test.com').exists())
		docente = User.objects.get(email='docente1@test.com')
		self.assertEqual(docente.profile.role, 'DOCENTE')

	def test_bulk_import_json(self):
		json_text = '[{"email": "json_student@test.com", "nombre": "Carlos", "rol": "ESTUDIANTE"}]'
		response = self.client.post('/admin/users/bulk-import/', {
			'raw_text': json_text,
			'default_role': 'ESTUDIANTE',
		})
		self.assertRedirects(response, '/admin/dashboard/')
		self.assertTrue(User.objects.filter(email='json_student@test.com').exists())


class GoogleLoginTests(TestCase):
	def test_google_login_get_renders_page(self):
		response = self.client.get('/google-login/')
		self.assertEqual(response.status_code, 200)

	def test_google_login_post_creates_and_logins_docente(self):
		response = self.client.post('/google-login/', {'email': 'docente_prueba@gmail.com'})
		self.assertRedirects(response, '/docente/dashboard/')
		user = User.objects.get(email='docente_prueba@gmail.com')
		self.assertEqual(user.profile.role, 'DOCENTE')
		self.assertTrue(self.client.session.get('gmail_oauth_connected'))

	def test_google_login_with_alias_and_local_password(self):
		response = self.client.post('/google-login/', {
			'email': 'profesor_local@gmail.com',
			'alias': 'Profe_Genio',
			'local_password': 'clave_offline_123',
		})
		self.assertRedirects(response, '/docente/dashboard/')
		user = User.objects.get(email='profesor_local@gmail.com')
		self.assertEqual(user.profile.alias, 'Profe_Genio')
		self.assertEqual(user.profile.display_name(), 'Profe_Genio')
		self.assertTrue(user.check_password('clave_offline_123'))

	def test_offline_local_login_with_local_password(self):
		# Create user via Gmail with local password
		self.client.post('/google-login/', {
			'email': 'examen_lan@gmail.com',
			'alias': 'Alumno_LAN',
			'local_password': 'mi_clave_lan_123',
		})
		self.client.logout()

		# Standard login offline without Google internet connection
		response = self.client.post('/login/', {
			'username': 'examen_lan',
			'password': 'mi_clave_lan_123',
		})
		self.assertRedirects(response, '/docente/dashboard/')


class AliasPrivacyTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='usuario_privado', email='privado@gmail.com', password='password123')
		self.profile = self.user.profile

	def test_display_name_uses_username_by_default(self):
		self.assertEqual(self.profile.display_name(), 'usuario_privado')

	def test_display_name_uses_alias_when_set(self):
		self.profile.alias = 'SuperProfesor2026'
		self.profile.save()
		self.assertEqual(self.profile.display_name(), 'SuperProfesor2026')

	def test_profile_form_updates_alias(self):
		self.client.force_login(self.user)
		response = self.client.post('/profile/', {
			'email': self.user.email,
			'alias': 'NuevoAliasPrivado',
			'first_name': 'Juan',
			'last_name': 'Pérez',
		})
		self.assertRedirects(response, '/profile/')
		self.profile.refresh_from_db()
		self.assertEqual(self.profile.alias, 'NuevoAliasPrivado')



