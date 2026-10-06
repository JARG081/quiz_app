from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Course, CourseTeacher, Enrollment
from .forms import CourseForm
from .services import request_course_enrollment, resolve_enrollment_request


class CourseFormTests(TestCase):
	def test_course_name_must_have_minimum_length(self):
		user = User.objects.create_user(username='admin', password='password123')
		form = CourseForm(data={'nombre': 'AB', 'descripcion': 'Curso corto'})

		self.assertFalse(form.is_valid())
		self.assertIn('nombre', form.errors)

	def test_course_form_accepts_valid_data(self):
		User.objects.create_user(username='admin2', password='password123')
		form = CourseForm(data={'nombre': 'Matemáticas', 'descripcion': 'Curso base'})

		self.assertTrue(form.is_valid())


class CourseEnrollmentServiceTests(TestCase):
	def setUp(self):
		self.teacher = User.objects.create_user(username='docente', password='password123')
		self.other_teacher = User.objects.create_user(username='otro_docente', password='password123')
		self.student = User.objects.create_user(username='estudiante', password='password123')
		self.course = Course.objects.create(nombre='Física', descripcion='Curso', creado_por=self.teacher)
		CourseTeacher.objects.create(course=self.course, teacher=self.teacher)

	def test_student_can_request_course_enrollment(self):
		enrollment, changed, message = request_course_enrollment(self.student, self.course)

		self.assertTrue(changed)
		self.assertEqual(enrollment.estado, Enrollment.PENDIENTE)
		self.assertIn('Solicitud enviada', message)

	def test_teacher_can_approve_pending_request(self):
		enrollment = Enrollment.objects.create(course=self.course, student=self.student, estado=Enrollment.PENDIENTE)

		success, message = resolve_enrollment_request(enrollment, self.teacher, approve=True)

		enrollment.refresh_from_db()
		self.assertTrue(success)
		self.assertEqual(enrollment.estado, Enrollment.APROBADA)
		self.assertIn('aprobada', message.lower())

	def test_teacher_cannot_manage_other_courses(self):
		other_course = Course.objects.create(nombre='Química', descripcion='Curso', creado_por=self.other_teacher)
		enrollment = Enrollment.objects.create(course=other_course, student=self.student, estado=Enrollment.PENDIENTE)

		success, message = resolve_enrollment_request(enrollment, self.teacher, approve=False)

		self.assertFalse(success)
		self.assertIn('permiso', message.lower())

	def test_get_does_not_remove_teacher_or_student(self):
		from users.models import Profile
		Profile.objects.filter(user=self.teacher).update(role='ADMIN')
		CourseTeacher.objects.create(course=self.course, teacher=self.other_teacher)
		enrollment = Enrollment.objects.create(
			course=self.course,
			student=self.student,
			estado=Enrollment.APROBADA,
		)
		self.client.force_login(self.teacher)

		remove_response = self.client.get(
			reverse('remove_teacher', args=[self.course.pk, self.other_teacher.pk])
		)
		unenroll_response = self.client.get(
			reverse('unenroll_student', args=[self.course.pk, self.student.pk])
		)

		self.assertEqual(remove_response.status_code, 405)
		self.assertEqual(unenroll_response.status_code, 405)
		self.assertTrue(CourseTeacher.objects.filter(pk__in=[self.course.teachers.get(teacher=self.other_teacher).pk]).exists())
		self.assertTrue(Enrollment.objects.filter(pk=enrollment.pk).exists())
