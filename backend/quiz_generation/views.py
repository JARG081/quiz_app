import json
import re
import threading
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from courses.models import Course, CourseTeacher
from quiz_platform.audit import log_action
from quizzes.models import Question, Quiz
from quizzes.services import sync_question_options, validate_question_options
from users.views import role_required

from .extraction import document_type_from_name, extract_text
from .forms import GenerateQuizForm, ImportQuizJsonForm
from .generator import generate_quiz
from .models import GenerationJob, SourceDocument

MAX_FILE_SIZE = 10 * 1024 * 1024


def _start_job(job_id):
    thread = threading.Thread(target=generate_quiz, args=(job_id,), daemon=True)
    thread.start()


@role_required('DOCENTE')
@require_http_methods(['GET', 'POST'])
def generate_form(request):
    courses = CourseTeacher.objects.filter(teacher=request.user).values_list('course_id', flat=True)
    form = GenerateQuizForm(request.POST or None, course_queryset=Course.objects.filter(pk__in=courses))
    if request.method == 'POST' and form.is_valid():
        files = request.FILES.getlist('archivos')
        if not 1 <= len(files) <= 3:
            form.add_error(None, 'Debes subir entre 1 y 3 archivos.')
        elif any(file.size > MAX_FILE_SIZE for file in files):
            form.add_error(None, 'Cada archivo debe pesar como máximo 10 MB.')
        else:
            documents = []
            try:
                for file in files:
                    document_type = document_type_from_name(file.name)
                    text = extract_text(file, document_type)
                    document = SourceDocument.objects.create(
                        course=form.cleaned_data['course'],
                        docente=request.user,
                        archivo=file,
                        nombre_original=file.name,
                        tipo=document_type,
                        texto_extraido=text,
                    )
                    documents.append(document)
                    log_action('SOURCE_UPLOAD', request.user, {'document_id': document.pk, 'tipo': document_type})
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                job = GenerationJob.objects.create(
                    docente=request.user,
                    course=form.cleaned_data['course'],
                    parametros={
                        'titulo': form.cleaned_data['titulo'],
                        'tipo': form.cleaned_data['tipo'],
                        'provider': form.cleaned_data.get('provider') or 'AUTO',
                        'instrucciones': form.cleaned_data['instrucciones'],
                    },

                    preguntas_solicitadas=form.cleaned_data['preguntas_solicitadas'],
                )
                job.documentos.set(documents)
                transaction.on_commit(lambda job_id=job.pk: _start_job(job_id))
                return redirect('generation_status', job_id=job.pk)
    return render(request, 'quiz_generation/generate_form.html', {'form': form})


def _owned_job(job_id, user):
    return get_object_or_404(GenerationJob, pk=job_id, docente=user)


def _mark_interrupted(job):
    if job.estado == GenerationJob.PROCESANDO and job.iniciado_en and job.iniciado_en < timezone.now() - timedelta(minutes=10):
        job.estado = GenerationJob.FALLIDO
        job.mensaje = 'Generación interrumpida después de 10 minutos.'
        job.finalizado_en = timezone.now()
        job.save(update_fields=['estado', 'mensaje', 'finalizado_en'])
    return job


@role_required('DOCENTE')
def generation_status(request, job_id):
    job = _mark_interrupted(_owned_job(job_id, request.user))
    return render(request, 'quiz_generation/generation_status.html', {'job': job})


@role_required('DOCENTE')
def generation_status_json(request, job_id):
    job = _mark_interrupted(_owned_job(job_id, request.user))
    return JsonResponse({
        'estado': job.estado,
        'mensaje': job.mensaje,
        'quiz_id': job.quiz_id,
    })


def _parse_and_validate_json(raw_text):
    raw_text = raw_text.strip()
    if '```' in raw_text:
        match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1).strip()
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'El texto no es un JSON válido: {exc}')

    if isinstance(data, list):
        questions_raw = data
    elif isinstance(data, dict):
        questions_raw = data.get('preguntas', [])
    else:
        raise ValueError("El JSON debe ser un objeto con la clave 'preguntas' o una lista de preguntas.")

    if not isinstance(questions_raw, list) or len(questions_raw) == 0:
        raise ValueError('El JSON no contiene ninguna pregunta.')

    valid = []
    seen = set()
    for item in questions_raw:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('tipo', 'MC')).upper()
        if kind not in ('MC', 'VF'):
            kind = 'MC'
        statement = str(item.get('enunciado', '')).strip()
        options_raw = item.get('opciones') or {}
        if not isinstance(options_raw, dict):
            continue
        if kind == 'VF':
            options = {
                'A': str(options_raw.get('A', 'Verdadero')).strip(),
                'B': str(options_raw.get('B', 'Falso')).strip(),
            }
        else:
            options = {letter: str(options_raw.get(letter, '')).strip() for letter in ('A', 'B', 'C', 'D')}

        correct = str(item.get('correcta', '')).strip().upper()
        explanation = str(item.get('explicacion', '')).strip()

        if not statement or statement.casefold() in seen:
            continue

        errors = validate_question_options(options, correct)
        if errors:
            continue

        seen.add(statement.casefold())
        valid.append({
            'enunciado': statement,
            'opciones': options,
            'correcta': correct,
            'explicacion': explanation,
        })

    if len(valid) == 0:
        raise ValueError('No se pudo extraer ninguna pregunta válida que cumpla las reglas de contenido.')

    return valid


@role_required('DOCENTE')
@require_http_methods(['GET', 'POST'])
def import_json_view(request):
    courses = CourseTeacher.objects.filter(teacher=request.user).values_list('course_id', flat=True)
    form = ImportQuizJsonForm(request.POST or None, request.FILES or None, course_queryset=Course.objects.filter(pk__in=courses))
    if request.method == 'POST' and form.is_valid():
        json_text = form.cleaned_data.get('json_text')
        archivo = form.cleaned_data.get('archivo_json')
        if archivo:
            try:
                raw_content = archivo.read().decode('utf-8')
            except Exception:
                form.add_error('archivo_json', 'El archivo no tiene un formato de texto UTF-8 válido.')
                raw_content = None
        else:
            raw_content = json_text

        if raw_content:
            try:
                valid_questions = _parse_and_validate_json(raw_content)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                with transaction.atomic():
                    quiz = Quiz.objects.create(
                        titulo=form.cleaned_data['titulo'],
                        descripcion=form.cleaned_data.get('descripcion') or 'Importado desde JSON de IA externa.',
                        course=form.cleaned_data['course'],
                        creado_por=request.user,
                        publicado=False,
                    )
                    for order, item in enumerate(valid_questions, start=1):
                        question = Question.objects.create(
                            quiz=quiz,
                            enunciado=item['enunciado'],
                            explicacion=item['explicacion'],
                            orden=order,
                        )
                        sync_question_options(question, item['opciones'], item['correcta'])
                log_action('QUIZ_IMPORT_JSON', request.user, {'quiz_id': quiz.pk, 'n': len(valid_questions)})
                messages.success(request, f"Quiz '{quiz.titulo}' creado exitosamente con {len(valid_questions)} preguntas importadas. Recuerda verificarlo para poder publicarlo.")
                return redirect('quiz_builder', quiz_id=quiz.pk)

    return render(request, 'quiz_generation/import_json.html', {'form': form})

