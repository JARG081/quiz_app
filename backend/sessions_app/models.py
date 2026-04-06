from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from quizzes.models import Quiz, Question, Option


class QuizSession(models.Model):
    ESPERA = 'ESPERA'
    EN_CURSO = 'EN_CURSO'
    FINALIZADO = 'FINALIZADO'
    ESTADO_CHOICES = [
        (ESPERA, 'En espera'),
        (EN_CURSO, 'En curso'),
        (FINALIZADO, 'Finalizado'),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='sessions')
    docente = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions_docente')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default=ESPERA)
    permitir_ingreso = models.BooleanField(default=True)
    mostrando_resultados = models.BooleanField(default=False)
    pregunta_actual = models.IntegerField(default=0)  # 0 = no iniciado, 1..N = index
    ultima_pregunta_inicio = models.DateTimeField(null=True, blank=True)
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_fin = models.DateTimeField(null=True, blank=True)
    codigo = models.CharField(max_length=8, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            import random, string
            self.codigo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Sesión {self.codigo} – {self.quiz.titulo}'

    def tiempo_restante(self):
        """Calcula segundos restantes para la pregunta actual."""
        if self.estado != self.EN_CURSO or not self.ultima_pregunta_inicio:
            return 0
        elapsed = (timezone.now() - self.ultima_pregunta_inicio).total_seconds()
        remaining = self.quiz.tiempo_por_pregunta - elapsed
        return max(0, int(remaining))

    def pregunta_actual_obj(self):
        """Retorna el objeto Question actual."""
        if self.pregunta_actual < 1:
            return None
        questions = list(self.quiz.questions.all())
        idx = self.pregunta_actual - 1
        if idx < len(questions):
            return questions[idx]
        return None

    def total_preguntas(self):
        return self.quiz.questions.count()

    def participantes_activos(self):
        return self.participants.filter(activo=True, expulsado=False)

    def tiempo_agotado(self):
        return self.tiempo_restante() == 0 and self.estado == self.EN_CURSO

    class Meta:
        ordering = ['-fecha_inicio', '-id']


class SessionParticipant(models.Model):
    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name='participants')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='participations')
    activo = models.BooleanField(default=True)
    expulsado = models.BooleanField(default=False)
    fecha_ingreso = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'student')

    def __str__(self):
        return f'{self.student.username} en {self.session.codigo}'


class LiveAnswer(models.Model):
    session = models.ForeignKey(QuizSession, on_delete=models.CASCADE, related_name='answers')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='live_answers')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    option = models.ForeignKey(Option, on_delete=models.CASCADE)
    puntaje = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'student', 'question')

    def __str__(self):
        return f'{self.student.username} → {self.option.letra}'
