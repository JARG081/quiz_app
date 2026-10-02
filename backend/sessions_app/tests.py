from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from courses.models import Course, Enrollment, CourseTeacher
from quizzes.models import Quiz
from .models import QuizSession
from .services import active_session_for_teacher, teacher_can_access_quiz, session_can_accept_student, get_session_by_code, pause_session, resume_session


class SessionServiceTests(TestCase):
	def setUp(self):
		self.teacher = User.objects.create_user(username='docente', password='password123')
		self.student = User.objects.create_user(username='estudiante', password='password123')
		self.course = Course.objects.create(nombre='Biología', descripcion='Curso', creado_por=self.teacher)
		CourseTeacher.objects.create(course=self.course, teacher=self.teacher)
		self.quiz = Quiz.objects.create(
			titulo='Quiz sesión',
			descripcion='Desc',
			course=self.course,
			creado_por=self.teacher,
			publicado=True,
			tiempo_por_pregunta=30,
		)

	def test_teacher_can_access_assigned_quiz(self):
		self.assertTrue(teacher_can_access_quiz(self.teacher, self.quiz))

	def test_active_session_for_teacher_returns_first_open_session(self):
		session = QuizSession.objects.create(quiz=self.quiz, docente=self.teacher)
		self.assertEqual(active_session_for_teacher(self.teacher), session)

	def test_get_session_by_code_returns_session(self):
		session = QuizSession.objects.create(quiz=self.quiz, docente=self.teacher)
		self.assertEqual(get_session_by_code(session.codigo).pk, session.pk)

	def test_student_cannot_join_without_enrollment(self):
		session = QuizSession.objects.create(quiz=self.quiz, docente=self.teacher)
		can_join, message = session_can_accept_student(session, self.student)
		self.assertFalse(can_join)
		self.assertIn('inscrito', message)

	def test_student_can_join_when_enrolled_and_session_open(self):
		session = QuizSession.objects.create(quiz=self.quiz, docente=self.teacher)
		Enrollment.objects.create(course=self.course, student=self.student, estado=Enrollment.APROBADA)

		can_join, message = session_can_accept_student(session, self.student)
		self.assertTrue(can_join)
		self.assertEqual(message, '')

	def test_pause_and_resume_session_freezes_time(self):
		base_time = datetime.now(dt_timezone.utc)
		session = QuizSession.objects.create(
			quiz=self.quiz,
			docente=self.teacher,
			estado=QuizSession.EN_CURSO,
			ultima_pregunta_inicio=base_time - timedelta(seconds=10),
		)

		with patch('sessions_app.services.timezone.now') as mock_now:
			mock_now.return_value = base_time
			self.assertTrue(pause_session(session))
			session.refresh_from_db()
			self.assertEqual(session.estado, QuizSession.PAUSADO)

			mock_now.return_value = base_time + timedelta(seconds=12)
			self.assertTrue(resume_session(session))
			session.refresh_from_db()
			self.assertEqual(session.estado, QuizSession.EN_CURSO)
			self.assertEqual(session.tiempo_pausa_acumulado, 12)
