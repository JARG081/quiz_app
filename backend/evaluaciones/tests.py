from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courses.models import Course, CourseTeacher, Enrollment
from quizzes.models import Option, Question, Quiz
from quizzes.services import compute_quiz_hash
from users.models import Profile

from .models import Asignacion, Intento
from .services import (
    asignaciones_disponibles,
    cerrar_intentos_vencidos,
    enviar_intento,
    guardar_respuesta,
    iniciar_intento,
    nota_final,
    puede_ver_respuestas,
)


class EvaluacionesServiceTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher_eval', password='password123')
        self.student = User.objects.create_user(username='student_eval', password='password123')
        self.other_student = User.objects.create_user(username='other_eval', password='password123')
        Profile.objects.filter(user=self.teacher).update(role=Profile.DOCENTE)
        Profile.objects.filter(user=self.student).update(role=Profile.ESTUDIANTE)
        Profile.objects.filter(user=self.other_student).update(role=Profile.ESTUDIANTE)
        self.course = Course.objects.create(nombre='Curso evaluación', descripcion='Curso', creado_por=self.teacher)
        CourseTeacher.objects.create(course=self.course, teacher=self.teacher)
        Enrollment.objects.create(course=self.course, student=self.student, estado=Enrollment.APROBADA)
        self.quiz = Quiz.objects.create(
            titulo='Quiz normal', descripcion='Descripción privada', course=self.course,
            creado_por=self.teacher, publicado=True,
        )
        for number in range(1, 6):
            question = Question.objects.create(
                quiz=self.quiz, enunciado=f'Pregunta {number}', explicacion='Explicación privada', orden=number,
            )
            Option.objects.create(question=question, letra='A', texto='Correcta', es_correcta=True)
            Option.objects.create(question=question, letra='B', texto='Incorrecta', es_correcta=False)
        now = timezone.now()
        self.assignment = Asignacion.objects.create(
            quiz=self.quiz, creado_por=self.teacher,
            abre_en=now - timedelta(minutes=5), cierra_en=now + timedelta(hours=1),
            intentos_permitidos=2,
        )

    def _answer_all(self, attempt, correct=True):
        for question in self.quiz.questions.all():
            option = question.options.get(letra='A' if correct else 'B')
            guardar_respuesta(attempt, question, option)

    def test_only_approved_students_see_available_assignments(self):
        self.assertIn(self.assignment, asignaciones_disponibles(self.student))
        self.assertNotIn(self.assignment, asignaciones_disponibles(self.other_student))

    def test_start_returns_progress_and_rejects_after_allowed_attempts(self):
        self.assignment.intentos_permitidos = 1
        self.assignment.save(update_fields=['intentos_permitidos'])
        attempt = iniciar_intento(self.assignment, self.student)
        self.assertEqual(iniciar_intento(self.assignment, self.student), attempt)
        enviar_intento(attempt)
        with self.assertRaises(ValidationError):
            iniciar_intento(self.assignment, self.student)

    def test_start_rejects_closed_window(self):
        self.assignment.cierra_en = timezone.now() - timedelta(seconds=1)
        self.assignment.save(update_fields=['cierra_en'])
        with self.assertRaises(ValidationError):
            iniciar_intento(self.assignment, self.student)

    def test_response_after_grace_period_is_rejected(self):
        attempt = iniciar_intento(self.assignment, self.student)
        attempt.limite_en = timezone.now() - timedelta(seconds=31)
        attempt.save(update_fields=['limite_en'])
        question = self.quiz.questions.first()
        with self.assertRaises(ValidationError):
            guardar_respuesta(attempt, question, question.options.first())

    def test_expired_attempt_is_submitted_automatically(self):
        attempt = iniciar_intento(self.assignment, self.student)
        attempt.limite_en = timezone.now() - timedelta(seconds=31)
        attempt.save(update_fields=['limite_en'])
        self.assertEqual(cerrar_intentos_vencidos(self.assignment), 1)
        attempt.refresh_from_db()
        self.assertEqual(attempt.estado, Intento.ENVIADO)
        self.assertTrue(attempt.enviado_automaticamente)

    def test_score_is_percentage_and_unanswered_is_incorrect(self):
        attempt = iniciar_intento(self.assignment, self.student)
        self._answer_all(attempt)
        enviar_intento(attempt)
        self.assertEqual(attempt.nota, Decimal('100.00'))
        self.assertEqual(attempt.correctas, 5)
        second = iniciar_intento(self.assignment, self.student)
        guardar_respuesta(second, self.quiz.questions.first(), self.quiz.questions.first().options.get(letra='B'))
        enviar_intento(second)
        self.assertEqual(second.nota, Decimal('0.00'))

    def test_best_attempt_is_returned(self):
        first = iniciar_intento(self.assignment, self.student)
        guardar_respuesta(first, self.quiz.questions.first(), self.quiz.questions.first().options.get(letra='A'))
        enviar_intento(first)
        second = iniciar_intento(self.assignment, self.student)
        self._answer_all(second)
        enviar_intento(second)
        self.assertEqual(nota_final(self.assignment, self.student), second)

    def test_closed_assignment_reveals_answers_only_after_submission(self):
        attempt = iniciar_intento(self.assignment, self.student)
        self.assertFalse(puede_ver_respuestas(attempt))
        enviar_intento(attempt)
        self.assertFalse(puede_ver_respuestas(attempt))
        self.assignment.cerrada_manualmente = True
        self.assignment.save(update_fields=['cerrada_manualmente'])
        self.assertTrue(puede_ver_respuestas(attempt))


class EvaluacionesViewTests(EvaluacionesServiceTests):
    def _verify_quiz(self):
        self.quiz.hash_verificado = compute_quiz_hash(self.quiz)
        self.quiz.verificado_en = timezone.now()
        self.quiz.save(update_fields=['hash_verificado', 'verificado_en'])

    def test_teacher_can_create_verified_assignment(self):
        self._verify_quiz()
        self.client.force_login(self.teacher)
        abre = timezone.now() - timedelta(minutes=1)
        cierra = timezone.now() + timedelta(hours=2)
        response = self.client.post(reverse('assignment_create', args=[self.quiz.pk]), {
            'abre_en': abre.strftime('%Y-%m-%dT%H:%M'),
            'cierra_en': cierra.strftime('%Y-%m-%dT%H:%M'),
            'intentos_permitidos': 1,
            'tiempo_limite_minutos': '',
            'mostrar_respuestas': Asignacion.AL_CIERRE,
        })
        self.assertRedirects(response, reverse('assignment_list'))
        self.assertEqual(Asignacion.objects.filter(quiz=self.quiz).count(), 2)

    def test_teacher_can_list_close_extend_and_delete_assignment(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('assignment_list')).status_code, 200)
        response = self.client.post(reverse('assignment_close', args=[self.assignment.pk]))
        self.assertRedirects(response, reverse('assignment_results', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertTrue(self.assignment.cerrada_manualmente)

        newer = (timezone.now() + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(reverse('assignment_extend', args=[self.assignment.pk]), {'cierra_en': newer})
        self.assertRedirects(response, reverse('assignment_results', args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.cerrada_manualmente)

        response = self.client.post(reverse('assignment_delete', args=[self.assignment.pk]))
        self.assertRedirects(response, reverse('assignment_list'))
        self.assertFalse(Asignacion.objects.filter(pk=self.assignment.pk).exists())

    def test_attempt_html_does_not_reveal_key_or_explanation(self):
        attempt = iniciar_intento(self.assignment, self.student)
        self.client.force_login(self.student)
        response = self.client.get(reverse('attempt_view', args=[attempt.pk]))
        self.assertNotContains(response, 'es_correcta')
        self.assertNotContains(response, 'Explicación privada')

    def test_student_cannot_access_another_student_attempt(self):
        attempt = iniciar_intento(self.assignment, self.student)
        self.client.force_login(self.other_student)
        response = self.client.get(reverse('attempt_view', args=[attempt.pk]))
        self.assertEqual(response.status_code, 404)

    def test_teacher_results_include_approved_student_without_attempt(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('assignment_results', args=[self.assignment.pk]))
        self.assertContains(response, self.student.username)
        self.assertContains(response, 'SIN_INICIAR')

    def test_answer_endpoint_updates_response_and_submit_redirects_review(self):
        attempt = iniciar_intento(self.assignment, self.student)
        question = self.quiz.questions.first()
        option = question.options.first()
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('answer_attempt', args=[attempt.pk]),
            data={'question_id': question.pk, 'option_id': option.pk},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('submit_attempt', args=[attempt.pk]))
        self.assertRedirects(response, reverse('attempt_review', args=[attempt.pk]))

    def test_assignment_create_requires_verified_quiz_and_teacher_course(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('assignment_create', args=[self.quiz.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('quiz_builder', args=[self.quiz.pk]))
        self.client.force_login(self.other_student)
        response = self.client.get(reverse('assignment_create', args=[self.quiz.pk]))
        self.assertEqual(response.status_code, 302)
