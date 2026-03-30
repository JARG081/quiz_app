from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from courses.models import Course


class Quiz(models.Model):
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='quizzes')
    creado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='quizzes_created')
    publicado = models.BooleanField(default=False)
    tiempo_por_pregunta = models.PositiveIntegerField(default=30, help_text='Segundos por pregunta')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.titulo

    def total_preguntas(self):
        return self.questions.count()

    def can_publish(self):
        return 5 <= self.total_preguntas() <= 20

    def clean(self):
        if self.publicado and not self.can_publish():
            raise ValidationError('El quiz debe tener entre 5 y 20 preguntas para publicarse.')

    class Meta:
        ordering = ['-fecha_creacion']


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='questions')
    enunciado = models.TextField()
    orden = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['orden']

    def __str__(self):
        return f'P{self.orden}: {self.enunciado[:60]}'

    def correct_option(self):
        return self.options.filter(es_correcta=True).first()


class Option(models.Model):
    LETRAS = [('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')]

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    texto = models.CharField(max_length=300)
    letra = models.CharField(max_length=1, choices=LETRAS)
    es_correcta = models.BooleanField(default=False)

    class Meta:
        ordering = ['letra']
        unique_together = ('question', 'letra')

    def __str__(self):
        return f'{self.letra}: {self.texto}'

    def clean(self):
        if self.es_correcta:
            existing = Option.objects.filter(
                question=self.question, es_correcta=True
            ).exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError('Solo puede haber una opción correcta por pregunta.')
