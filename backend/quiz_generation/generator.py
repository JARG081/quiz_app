import json
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db import close_old_connections
from django.utils import timezone

from quiz_platform.audit import log_action
from quizzes.models import Question, Quiz
from quizzes.services import sync_question_options, validate_question_options

from .models import GenerationJob
from .providers import ProviderError, ProviderNotConfigured, generate_with_retries, get_provider

SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'preguntas': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'tipo': {'type': 'STRING'},
                    'enunciado': {'type': 'STRING'},
                    'opciones': {'type': 'OBJECT'},
                    'correcta': {'type': 'STRING'},
                    'explicacion': {'type': 'STRING'},
                },
                'required': ['tipo', 'enunciado', 'opciones', 'correcta', 'explicacion'],
            },
        },
    },
    'required': ['preguntas'],
}


def _prompt(text, job):
    return f'''Genera un quiz en español usando SOLO el contenido fuente siguiente.
Devuelve JSON con esta forma exacta: {{"preguntas": [{{"tipo": "MC" o "VF", "enunciado": str, "opciones": {{"A": str, "B": str, "C": str, "D": str}}, "correcta": "A".."D", "explicacion": str}}]}}.
Para VF usa solo A=Verdadero y B=Falso. No inventes datos. Genera {job.preguntas_solicitadas} preguntas del tipo {job.parametros.get('tipo', 'MIXTO')}.
Instrucciones adicionales: {job.parametros.get('instrucciones', '')}

CONTENIDO FUENTE:
{text}'''


def _valid_questions(payload, job):
    questions = payload.get('preguntas', []) if isinstance(payload, dict) else []
    valid = []
    seen = set()
    requested_type = job.parametros.get('tipo', 'MIXTO')
    for item in questions:
        if not isinstance(item, dict):
            continue
        kind = item.get('tipo')
        if requested_type == 'MC' and kind != 'MC' or requested_type == 'VF' and kind != 'VF':
            continue
        statement = str(item.get('enunciado', '')).strip()
        options = item.get('opciones') or {}
        if kind == 'VF':
            options = {'A': str(options.get('A', 'Verdadero')), 'B': str(options.get('B', 'Falso'))}
        else:
            options = {letter: str(options.get(letter, '')).strip() for letter in ('A', 'B', 'C', 'D')}
        correct = str(item.get('correcta', '')).strip().upper()
        if not statement or statement.casefold() in seen:
            continue
        if validate_question_options(options, correct):
            continue
        seen.add(statement.casefold())
        valid.append({
            'enunciado': statement,
            'opciones': options,
            'correcta': correct,
            'explicacion': str(item.get('explicacion', '')).strip(),
        })
    return valid[:job.preguntas_solicitadas]


def generate_quiz(job_id):
    close_old_connections()
    try:
        job = GenerationJob.objects.prefetch_related('documentos').select_related('course', 'docente').get(pk=job_id)
        job.estado = GenerationJob.PROCESANDO
        job.iniciado_en = timezone.now()
        selected_provider = job.parametros.get('provider')
        provider = get_provider(selected_provider if selected_provider and selected_provider != 'AUTO' else None)

        source = '\n\n'.join(document.texto_extraido for document in job.documentos.all())
        max_chars = settings.QUIZ_AI_MAX_SOURCE_CHARS
        warning = ''
        if len(source) > max_chars:
            source = source[:max_chars]
            warning = f' El texto fuente fue truncado a {max_chars} caracteres.'
        payload = generate_with_retries(provider, _prompt(source, job), SCHEMA)
        valid = _valid_questions(payload, job)
        if len(valid) < 5:
            raise ProviderError('Se generaron menos de 5 preguntas válidas.')
        with transaction.atomic():
            quiz = Quiz.objects.create(
                titulo=job.parametros['titulo'],
                descripcion='Generado desde archivos. Verifica el contenido antes de publicar.',
                course=job.course,
                creado_por=job.docente,
                publicado=False,
            )
            for order, item in enumerate(valid, start=1):
                question = Question.objects.create(
                    quiz=quiz,
                    enunciado=item['enunciado'],
                    explicacion=item['explicacion'],
                    orden=order,
                )
                sync_question_options(question, item['opciones'], item['correcta'])
            job.quiz = quiz
            job.preguntas_generadas = len(valid)
            job.estado = GenerationJob.COMPLETADO
            job.mensaje = f'Generación completada.{warning}'
            job.finalizado_en = timezone.now()
            job.save(update_fields=['quiz', 'preguntas_generadas', 'estado', 'mensaje', 'finalizado_en'])
        log_action('QUIZ_GENERATE', job.docente, {'job_id': job.pk, 'quiz_id': quiz.pk, 'n': len(valid)})
    except Exception as exc:
        GenerationJob.objects.filter(pk=job_id).update(
            estado=GenerationJob.FALLIDO,
            mensaje=str(exc),
            finalizado_en=timezone.now(),
        )
        job = GenerationJob.objects.filter(pk=job_id).select_related('docente').first()
        if job:
            log_action('QUIZ_GENERATE_FAIL', job.docente, {'job_id': job_id, 'mensaje': str(exc)})
    finally:
        close_old_connections()
