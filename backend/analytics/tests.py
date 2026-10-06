from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from courses.models import Course, CourseTeacher, Enrollment
from evaluaciones.models import Asignacion, Intento
from evaluaciones.services import enviar_intento, iniciar_intento
from quizzes.models import Option, Question, Quiz
from users.models import Profile


class AnalyticsEvaluacionesTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='analytics_teacher', password='password123')
        self.student = User.objects.create_user(username='analytics_student', password='password123')
        Profile.objects.filter(user=self.teacher).update(role=Profile.DOCENTE)
        Profile.objects.filter(user=self.student).update(role=Profile.ESTUDIANTE)
        self.course = Course.objects.create(nombre='Analytics', descripcion='Curso', creado_por=self.teacher)
        CourseTeacher.objects.create(course=self.course, teacher=self.teacher)
        Enrollment.objects.create(course=self.course, student=self.student, estado=Enrollment.APROBADA)
        self.quiz = Quiz.objects.create(titulo='Quiz analytics', course=self.course, creado_por=self.teacher, publicado=True)
        question = Question.objects.create(quiz=self.quiz, enunciado='Pregunta', orden=1)
        Option.objects.create(question=question, letra='A', texto='Correcta', es_correcta=True)
        Option.objects.create(question=question, letra='B', texto='Incorrecta', es_correcta=False)
        now = timezone.now()
        self.assignment = Asignacion.objects.create(
            quiz=self.quiz, creado_por=self.teacher,
            abre_en=now - timedelta(minutes=5), cierra_en=now + timedelta(hours=1),
        )

    def _submit_attempt(self):
        attempt = iniciar_intento(self.assignment, self.student)
        question = self.quiz.questions.first()
        response = self.client.post(
            reverse('answer_attempt', args=[attempt.pk]),
            data={'question_id': question.pk, 'option_id': question.options.first().pk},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        enviar_intento(attempt)

    def test_student_stats_uses_final_attempt_data(self):
        self.client.force_login(self.student)
        self._submit_attempt()
        response = self.client.get(reverse('student_stats'))
        self.assertContains(response, 'Quiz analytics')
        self.assertContains(response, '100,00%')

    def test_teacher_stats_filters_by_course_and_uses_intentos(self):
        self.client.force_login(self.student)
        self._submit_attempt()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('docente_stats'), {'course': self.course.pk})
        self.assertContains(response, 'Quiz analytics')
        self.assertContains(response, '1/1 enviados')
        self.assertContains(response, '1/1 aciertos')

    def test_teacher_stats_query_count_does_not_depend_on_assignments(self):
        self.client.force_login(self.teacher)
        with CaptureQueriesContext(connection) as first_context:
            self.client.get(reverse('docente_stats'))
        now = timezone.now()
        Asignacion.objects.create(
            quiz=self.quiz, creado_por=self.teacher,
            abre_en=now - timedelta(minutes=5), cierra_en=now + timedelta(hours=1),
        )
        with CaptureQueriesContext(connection) as second_context:
            self.client.get(reverse('docente_stats'))
        self.assertEqual(len(first_context), len(second_context))


class AdminAnalyticsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin_stats', password='password123')
        self.teacher = User.objects.create_user(username='admin_teacher', password='password123')
        self.student = User.objects.create_user(username='admin_student', password='password123')
        Profile.objects.filter(user=self.admin).update(role=Profile.ADMIN)
        Profile.objects.filter(user=self.teacher).update(role=Profile.DOCENTE)
        Profile.objects.filter(user=self.student).update(role=Profile.ESTUDIANTE)
        self.course = Course.objects.create(nombre='Curso admin', descripcion='', creado_por=self.admin)
        CourseTeacher.objects.create(course=self.course, teacher=self.teacher)
        Enrollment.objects.create(course=self.course, student=self.student, estado=Enrollment.APROBADA)
        self.quiz = Quiz.objects.create(titulo='Quiz admin', course=self.course, creado_por=self.teacher, publicado=True)
        question = Question.objects.create(quiz=self.quiz, enunciado='Pregunta admin', orden=1)
        Option.objects.create(question=question, letra='A', texto='Correcta', es_correcta=True)
        Option.objects.create(question=question, letra='B', texto='Incorrecta', es_correcta=False)
        now = timezone.now()
        self.assignment = Asignacion.objects.create(
            quiz=self.quiz, creado_por=self.teacher,
            abre_en=now - timedelta(days=1), cierra_en=now + timedelta(days=1),
        )
        Intento.objects.create(
            asignacion=self.assignment, estudiante=self.student, numero=1,
            estado=Intento.ENVIADO, enviado_en=now, correctas=1, total=1,
            nota=80, hash_contenido='h' * 64,
        )

    def test_admin_sees_metrics_and_filtered_course_table(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_stats'), {'course': self.course.pk, 'docente': self.teacher.pk})
        self.assertContains(response, 'Curso admin')
        self.assertContains(response, '80')

    def test_admin_course_detail_shows_teacher_and_lowest_questions(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_course_detail', args=[self.course.pk]))
        self.assertContains(response, 'admin_teacher')
        self.assertContains(response, 'Pregunta admin')

    def test_admin_can_export_xlsx(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_course_export'), {'course': self.course.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(response.content))
        self.assertEqual(workbook.active['A2'].value, 'Curso admin')

    def test_non_admin_cannot_access_admin_statistics(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('admin_stats')).status_code, 302)

    def test_admin_stats_query_count_is_stable_when_adding_assignment(self):
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as first_context:
            self.client.get(reverse('admin_stats'))
        now = timezone.now()
        Asignacion.objects.create(
            quiz=self.quiz, creado_por=self.teacher,
            abre_en=now - timedelta(days=1), cierra_en=now + timedelta(days=1),
        )
        with CaptureQueriesContext(connection) as second_context:
            self.client.get(reverse('admin_stats'))
        self.assertEqual(len(first_context), len(second_context))
