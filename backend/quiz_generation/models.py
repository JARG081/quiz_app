from django.contrib.auth.models import User
from django.db import models

from courses.models import Course
from quizzes.models import Quiz


class SourceDocument(models.Model):
    PDF = 'PDF'
    DOCX = 'DOCX'
    PPTX = 'PPTX'
    TXT = 'TXT'
    TYPE_CHOICES = [(value, value) for value in (PDF, DOCX, PPTX, TXT)]

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='source_documents')
    docente = models.ForeignKey(User, on_delete=models.PROTECT, related_name='source_documents')
    archivo = models.FileField(upload_to='sources/')
    nombre_original = models.CharField(max_length=255)
    tipo = models.CharField(max_length=4, choices=TYPE_CHOICES)
    texto_extraido = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)


class GenerationJob(models.Model):
    PENDIENTE = 'PENDIENTE'
    PROCESANDO = 'PROCESANDO'
    COMPLETADO = 'COMPLETADO'
    FALLIDO = 'FALLIDO'
    STATUS_CHOICES = [(value, value.title()) for value in (PENDIENTE, PROCESANDO, COMPLETADO, FALLIDO)]

    docente = models.ForeignKey(User, on_delete=models.PROTECT, related_name='quiz_generation_jobs')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='quiz_generation_jobs')
    documentos = models.ManyToManyField(SourceDocument, related_name='generation_jobs')
    quiz = models.ForeignKey(Quiz, on_delete=models.SET_NULL, null=True, blank=True, related_name='generation_jobs')
    parametros = models.JSONField(default=dict)
    estado = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDIENTE)
    mensaje = models.TextField(blank=True)
    preguntas_solicitadas = models.PositiveSmallIntegerField(default=5)
    preguntas_generadas = models.PositiveSmallIntegerField(default=0)
    creado_en = models.DateTimeField(auto_now_add=True)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    finalizado_en = models.DateTimeField(null=True, blank=True)
