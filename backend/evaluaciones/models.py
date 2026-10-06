from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from quizzes.models import Option, Question, Quiz


class Asignacion(models.Model):
    NORMAL = 'NORMAL'
    MODO_CHOICES = [(NORMAL, 'Normal')]

    AL_ENVIAR = 'AL_ENVIAR'
    AL_CIERRE = 'AL_CIERRE'
    NUNCA = 'NUNCA'
    MOSTRAR_RESPUESTAS_CHOICES = [
        (AL_ENVIAR, 'Al enviar'),
        (AL_CIERRE, 'Al cierre'),
        (NUNCA, 'Nunca'),
    ]

    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name='asignaciones')
    creado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='asignaciones_creadas')
    modo = models.CharField(max_length=10, choices=MODO_CHOICES, default=NORMAL)
    abre_en = models.DateTimeField()
    cierra_en = models.DateTimeField()
    intentos_permitidos = models.PositiveSmallIntegerField(default=1)
    tiempo_limite_minutos = models.PositiveSmallIntegerField(null=True, blank=True)
    mostrar_respuestas = models.CharField(
        max_length=12,
        choices=MOSTRAR_RESPUESTAS_CHOICES,
        default=AL_CIERRE,
    )
    cerrada_manualmente = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)

    def clean(self):
        errors = {}
        if self.cierra_en and self.abre_en and self.cierra_en <= self.abre_en:
            errors['cierra_en'] = 'La fecha de cierre debe ser posterior a la apertura.'
        if not 1 <= self.intentos_permitidos <= 5:
            errors['intentos_permitidos'] = 'Los intentos permitidos deben estar entre 1 y 5.'
        if self.tiempo_limite_minutos is not None and not 1 <= self.tiempo_limite_minutos <= 180:
            errors['tiempo_limite_minutos'] = 'El límite debe estar entre 1 y 180 minutos.'
        if errors:
            raise ValidationError(errors)

    def esta_abierta(self, now=None):
        now = now or timezone.now()
        return not self.cerrada_manualmente and self.abre_en <= now < self.cierra_en

    def estado(self, now=None):
        now = now or timezone.now()
        if self.cerrada_manualmente or now >= self.cierra_en:
            return 'CERRADA'
        if now < self.abre_en:
            return 'PROGRAMADA'
        return 'ABIERTA'

    def __str__(self):
        return f'{self.quiz.titulo} - {self.quiz.course.nombre}'


class Intento(models.Model):
    EN_PROGRESO = 'EN_PROGRESO'
    ENVIADO = 'ENVIADO'
    ESTADO_CHOICES = [(EN_PROGRESO, 'En progreso'), (ENVIADO, 'Enviado')]

    asignacion = models.ForeignKey(Asignacion, on_delete=models.CASCADE, related_name='intentos')
    estudiante = models.ForeignKey(User, on_delete=models.PROTECT, related_name='intentos')
    numero = models.PositiveSmallIntegerField()
    iniciado_en = models.DateTimeField(auto_now_add=True)
    enviado_en = models.DateTimeField(null=True, blank=True)
    limite_en = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default=EN_PROGRESO)
    enviado_automaticamente = models.BooleanField(default=False)
    correctas = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    nota = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hash_contenido = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['asignacion', 'estudiante', 'numero'], name='unique_intento_por_estudiante'),
        ]
        ordering = ['numero', 'id']

    def __str__(self):
        return f'{self.estudiante.username} - {self.asignacion.quiz.titulo} - {self.numero}'


class RespuestaIntento(models.Model):
    intento = models.ForeignKey(Intento, on_delete=models.CASCADE, related_name='respuestas')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='respuestas_intento')
    option = models.ForeignKey(Option, on_delete=models.PROTECT, null=True, blank=True, related_name='respuestas_intento')
    es_correcta = models.BooleanField(default=False)
    respondida_en = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['intento', 'question'], name='unique_respuesta_por_pregunta'),
        ]

    def __str__(self):
        return f'{self.intento} - P{self.question.orden}'
