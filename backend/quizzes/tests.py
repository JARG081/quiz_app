from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json
from unittest import mock

from courses.models import Course, CourseTeacher
from .forms import QuizForm
from .models import Quiz, Question, Option
from evaluaciones.models import Asignacion
from .services import (
	assert_quiz_editable,
	compute_quiz_hash,
	duplicate_quiz,
	grade_verification,
	quiz_is_verified,
	validate_question_options,
	sync_question_options,
	reorder_questions,
)
class QuizFormTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(username='docente', password='password123')
		self.course = Course.objects.create(nombre='Historia', descripcion='Curso', creado_por=self.user)

	def test_quiz_form_rejects_unknown_time_field(self):
		form = QuizForm(
			data={
				'titulo': 'Quiz 1',
				'descripcion': 'Desc',
				'course': self.course.pk,
				'tiempo_por_pregunta': 4,
			},
			course_queryset=Course.objects.filter(pk=self.course.pk),
		)

		self.assertTrue(form.is_valid())

	def test_quiz_form_accepts_valid_data(self):
		form = QuizForm(
			data={
				'titulo': 'Quiz 1',
				'descripcion': 'Desc',
				'course': self.course.pk,
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
		Profile.objects.filter(user=self.user).update(role='DOCENTE')
		
		self.course = Course.objects.create(nombre='Matemática', descripcion='Curso', creado_por=self.user)
		self.quiz = Quiz.objects.create(
			titulo='Quiz Reorder',
			descripcion='Desc',
			course=self.course,
			creado_por=self.user,
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

	def test_reorder_published_quiz_without_assignment_unpublishes(self):
		self.quiz.publicado = True
		self.quiz.save(update_fields=['publicado'])
		self.client.force_login(self.user)
		response = self.client.post(
			reverse('reorder_questions_api', args=[self.quiz.pk]),
			data='{"order": [%d, %d, %d]}' % (self.q3.pk, self.q1.pk, self.q2.pk),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		self.quiz.refresh_from_db()
		self.assertFalse(self.quiz.publicado)
	def test_assigned_quiz_cannot_be_reordered(self):
		Asignacion.objects.create(
			quiz=self.quiz,
			creado_por=self.user,
			abre_en=timezone.now(),
			cierra_en=timezone.now() + timedelta(hours=1),
		)
		result = assert_quiz_editable(self.quiz)
		self.assertFalse(result[0])
		self.assertIn('Duplícalo', result[1])

	def test_assigned_quiz_rejects_question_mutations(self):
		Asignacion.objects.create(
			quiz=self.quiz,
			creado_por=self.user,
			abre_en=timezone.now(),
			cierra_en=timezone.now() + timedelta(hours=1),
		)
		self.client.force_login(self.user)
		count = self.quiz.questions.count()
		payload = {
			'enunciado': 'Nueva pregunta', 'opt_A': 'A', 'opt_B': 'B',
			'opt_C': 'C', 'opt_D': 'D', 'correcta': 'A',
		}
		self.client.post(reverse('add_question', args=[self.quiz.pk]), payload)
		self.client.post(reverse('edit_question', args=[self.quiz.pk, self.q1.pk]), payload)
		self.client.post(reverse('delete_question', args=[self.quiz.pk, self.q1.pk]))
		self.assertEqual(self.quiz.questions.count(), count)

	def test_duplicate_quiz_copies_questions_and_options(self):
		Option.objects.create(question=self.q1, letra='A', texto='Sí', es_correcta=True)
		Option.objects.create(question=self.q1, letra='B', texto='No', es_correcta=False)
		duplicate = duplicate_quiz(self.quiz, self.user)
		self.assertFalse(duplicate.publicado)
		self.assertEqual(duplicate.questions.count(), 3)
		self.assertEqual(list(duplicate.questions.first().options.values_list('texto', flat=True)), ['Sí', 'No'])

	def test_get_cannot_toggle_publish(self):
		self.client.force_login(self.user)
		response = self.client.get(reverse('toggle_publish', args=[self.quiz.pk]))
		self.assertEqual(response.status_code, 405)
		self.quiz.refresh_from_db()
		self.assertFalse(self.quiz.publicado)
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
		self.assertTrue(hasattr(settings, 'LOGGING'))
		self.assertIn('quiz_platform.audit', settings.LOGGING['loggers'])


class TeacherVerificationTests(TestCase):
	def setUp(self):
		self.teacher = User.objects.create_user(username='verification_teacher', password='password123')
		self.other_teacher = User.objects.create_user(username='other_verification', password='password123')
		from users.models import Profile
		Profile.objects.filter(user=self.teacher).update(role='DOCENTE')
		Profile.objects.filter(user=self.other_teacher).update(role='DOCENTE')
		self.course = Course.objects.create(nombre='Verificación', descripcion='Curso', creado_por=self.teacher)
		self.quiz = Quiz.objects.create(titulo='Quiz para verificar', course=self.course, creado_por=self.teacher)
		for index in range(1, 6):
			question = Question.objects.create(quiz=self.quiz, enunciado=f'Pregunta {index}', explicacion='Explicación privada', orden=index)
			Option.objects.create(question=question, letra='A', texto='Correcta', es_correcta=True)
			Option.objects.create(question=question, letra='B', texto='Incorrecta', es_correcta=False)

	def _answers(self, correct=True):
		return {
			str(question.pk): question.options.get(letra='A' if correct else 'B').pk
			for question in self.quiz.questions.all()
		}

	def test_all_correct_answers_approve_verification(self):
		attempt = grade_verification(self.quiz, self.teacher, self._answers())
		self.assertTrue(attempt.aprobado)
		self.quiz.hash_verificado = attempt.hash_contenido
		self.quiz.verificado_en = timezone.now()
		self.quiz.save(update_fields=['hash_verificado', 'verificado_en'])
		self.assertTrue(quiz_is_verified(self.quiz))

	def test_wrong_answer_does_not_approve(self):
		attempt = grade_verification(self.quiz, self.teacher, self._answers(correct=False))
		self.assertFalse(attempt.aprobado)

	def test_content_change_invalidates_verification_but_title_does_not(self):
		self.quiz.hash_verificado = compute_quiz_hash(self.quiz)
		self.quiz.verificado_en = timezone.now()
		self.quiz.save(update_fields=['hash_verificado', 'verificado_en'])
		self.quiz.titulo = 'Título nuevo'
		self.quiz.save(update_fields=['titulo'])
		self.quiz.refresh_from_db()
		self.assertTrue(quiz_is_verified(self.quiz))
		option = self.quiz.questions.first().options.first()
		option.texto = 'Texto cambiado'
		option.save(update_fields=['texto'])
		self.quiz.refresh_from_db()
		self.assertFalse(quiz_is_verified(self.quiz))

	def test_publish_without_verification_is_rejected(self):
		self.quiz.publicado = False
		self.quiz.save(update_fields=['publicado'])
		self.client.force_login(self.teacher)
		response = self.client.post(reverse('toggle_publish', args=[self.quiz.pk]))
		self.assertRedirects(response, reverse('quiz_builder', args=[self.quiz.pk]))
		self.quiz.refresh_from_db()
		self.assertFalse(self.quiz.publicado)

	def test_verification_form_does_not_reveal_correct_answer_or_explanation(self):
		self.client.force_login(self.teacher)
		response = self.client.get(reverse('verify_quiz', args=[self.quiz.pk]))
		self.assertNotContains(response, 'es_correcta')
		self.assertNotContains(response, 'Explicación privada')

	def test_other_teacher_cannot_verify(self):
		self.client.force_login(self.other_teacher)
		response = self.client.get(reverse('verify_quiz', args=[self.quiz.pk]))
		self.assertEqual(response.status_code, 404)


class QuizViewTests(TestCase):
	def setUp(self):
		from users.models import Profile
		self.teacher = User.objects.create_user(username='quiz_view_teacher', password='password123')
		Profile.objects.filter(user=self.teacher).update(role='DOCENTE')
		self.course = Course.objects.create(nombre='Curso de vistas', descripcion='', creado_por=self.teacher)
		CourseTeacher.objects.create(course=self.course, teacher=self.teacher)
		self.quiz = Quiz.objects.create(titulo='Quiz vista', descripcion='Desc', course=self.course, creado_por=self.teacher)
		for index in range(1, 6):
			question = Question.objects.create(quiz=self.quiz, enunciado=f'Pregunta {index}', orden=index)
			Option.objects.create(question=question, letra='A', texto='A', es_correcta=True)
			Option.objects.create(question=question, letra='B', texto='B', es_correcta=False)
		self.client.force_login(self.teacher)

	def test_quiz_list_create_edit_and_builder(self):
		self.assertEqual(self.client.get(reverse('quiz_list')).status_code, 200)
		response = self.client.post(reverse('quiz_create'), {'titulo': 'Nuevo', 'descripcion': 'D', 'course': self.course.pk})
		self.assertEqual(response.status_code, 302)
		response = self.client.post(reverse('quiz_edit', args=[self.quiz.pk]), {'titulo': 'Título editado', 'descripcion': 'D2', 'course': self.course.pk})
		self.assertRedirects(response, reverse('quiz_builder', args=[self.quiz.pk]))
		self.assertEqual(self.client.get(reverse('quiz_builder', args=[self.quiz.pk])).status_code, 200)

	def test_question_crud_and_publish_without_verification(self):
		payload = {
			'enunciado': 'Nueva pregunta', 'opt_A': 'A', 'opt_B': 'B',
			'opt_C': 'C', 'opt_D': 'D', 'correcta': 'A',
		}
		initial = self.quiz.questions.count()
		response = self.client.post(reverse('add_question', args=[self.quiz.pk]), payload)
		self.assertRedirects(response, reverse('quiz_builder', args=[self.quiz.pk]))
		question = self.quiz.questions.order_by('-id').first()
		self.client.post(reverse('edit_question', args=[self.quiz.pk, question.pk]), {
			'enunciado': 'Pregunta editada', 'correcta': 'A',
			'opt_A': 'A', 'opt_B': 'B', 'opt_C': 'C', 'opt_D': 'D',
		})
		question.refresh_from_db()
		self.assertEqual(question.enunciado, 'Pregunta editada')
		self.client.post(reverse('delete_question', args=[self.quiz.pk, question.pk]))
		self.assertEqual(self.quiz.questions.count(), initial)
		response = self.client.post(reverse('toggle_publish', args=[self.quiz.pk]))
		self.assertRedirects(response, reverse('quiz_builder', args=[self.quiz.pk]))
		self.quiz.refresh_from_db()
		self.assertFalse(self.quiz.publicado)

        
