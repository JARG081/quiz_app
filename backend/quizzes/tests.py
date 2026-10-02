from django.contrib.auth.models import User
from django.test import TestCase
import json
from unittest import mock

from courses.models import Course
from .forms import QuizForm
from .models import Quiz, Question, Option
from .services import validate_question_options, sync_question_options, reorder_questions


class QuizFormTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='docente', password='password123')
		self.course = Course.objects.create(nombre='Historia', descripcion='Curso', creado_por=self.user)

	def test_quiz_form_rejects_time_outside_range(self):
		form = QuizForm(
			data={
				'titulo': 'Quiz 1',
				'descripcion': 'Desc',
				'course': self.course.pk,
				'tiempo_por_pregunta': 4,
			},
			course_queryset=Course.objects.filter(pk=self.course.pk),
		)

		self.assertFalse(form.is_valid())
		self.assertIn('tiempo_por_pregunta', form.errors)

	def test_quiz_form_accepts_valid_data(self):
		form = QuizForm(
			data={
				'titulo': 'Quiz 1',
				'descripcion': 'Desc',
				'course': self.course.pk,
				'tiempo_por_pregunta': 30,
			},
			course_queryset=Course.objects.filter(pk=self.course.pk),
		)

		self.assertTrue(form.is_valid())


class QuestionServiceTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='docente2', password='password123')
		self.course = Course.objects.create(nombre='Ciencia', descripcion='Curso', creado_por=self.user)
		self.quiz = Quiz.objects.create(
			titulo='Quiz',
			descripcion='Desc',
			course=self.course,
			creado_por=self.user,
			tiempo_por_pregunta=30,
		)
		self.question = Question.objects.create(quiz=self.quiz, enunciado='Pregunta', orden=1)

	def test_validate_question_options_for_multiple_choice(self):
		texts = {'A': 'Uno', 'B': 'Dos', 'C': 'Tres', 'D': 'Cuatro'}
		self.assertIsNone(validate_question_options(texts, 'C'))

	def test_sync_question_options_replaces_removed_letters(self):
		sync_question_options(self.question, {'A': 'Verdadero', 'B': 'Falso'}, 'A')
		self.assertEqual(self.question.options.count(), 2)
		self.assertFalse(self.question.options.filter(letra__in=['C', 'D']).exists())


class QuestionReorderingTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='docente3', password='password123')
		from users.models import Profile
		Profile.objects.get_or_create(user=self.user, defaults={'role': 'DOCENTE'})
		
		self.course = Course.objects.create(nombre='Matemática', descripcion='Curso', creado_por=self.user)
		self.quiz = Quiz.objects.create(
			titulo='Quiz Reorder',
			descripcion='Desc',
			course=self.course,
			creado_por=self.user,
			tiempo_por_pregunta=30,
		)
		# Create 3 questions with orden 1, 2, 3
		self.q1 = Question.objects.create(quiz=self.quiz, enunciado='Pregunta 1', orden=1)
		self.q2 = Question.objects.create(quiz=self.quiz, enunciado='Pregunta 2', orden=2)
		self.q3 = Question.objects.create(quiz=self.quiz, enunciado='Pregunta 3', orden=3)

	def test_reorder_questions_service(self):
		# Reorder to 3, 1, 2
		result = reorder_questions(self.quiz, [self.q3.pk, self.q1.pk, self.q2.pk])
		
		self.assertTrue(result['success'])
		self.q1.refresh_from_db()
		self.q2.refresh_from_db()
		self.q3.refresh_from_db()
		self.assertEqual(self.q3.orden, 1)
		self.assertEqual(self.q1.orden, 2)
		self.assertEqual(self.q2.orden, 3)

	def test_reorder_questions_rejects_invalid_ids(self):
		result = reorder_questions(self.quiz, [999, 1000])
		self.assertFalse(result['success'])


class AuditingModuleTests(TestCase):
	"""Test that audit logging infrastructure is properly set up."""
	
	def test_audit_module_exists(self):
		"""Verify the audit module can be imported."""
		from quiz_platform import audit
		self.assertTrue(hasattr(audit, 'log_action'))
		self.assertTrue(callable(audit.log_action))
	
	def test_audit_logger_configured(self):
		"""Verify the audit logger is configured in Django logging."""
		from django.conf import settings
		self.assertIn('LOGGING', settings.__dict__)
		self.assertIn('quiz_platform.audit', settings.LOGGING['loggers'])
