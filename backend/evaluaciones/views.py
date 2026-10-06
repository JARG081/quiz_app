import json

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.views.decorators.http import require_POST

from courses.models import CourseTeacher, Enrollment
from quiz_platform.audit import log_action
from quizzes.models import Option, Question, Quiz
from quizzes.services import quiz_is_verified
from users.views import role_required

from .forms import AsignacionForm
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


def _teacher_can_access(teacher, quiz):
    return CourseTeacher.objects.filter(course=quiz.course, teacher=teacher).exists()


def _assignment_for_teacher(assignment_id, teacher):
    return get_object_or_404(
        Asignacion.objects.select_related('quiz', 'quiz__course'),
        pk=assignment_id,
        quiz__course__teachers__teacher=teacher,
    )


@role_required('DOCENTE')
def assignment_create(request, quiz_id):
    quiz = get_object_or_404(Quiz.objects.select_related('course'), pk=quiz_id, publicado=True)
    if not _teacher_can_access(request.user, quiz):
        return redirect('quiz_list')
    if not quiz_is_verified(quiz):
        messages.error(request, 'El quiz debe estar verificado antes de asignarse.')
        return redirect('quiz_builder', quiz_id=quiz.pk)
    form = AsignacionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        assignment = form.save(commit=False)
        assignment.quiz = quiz
        assignment.creado_por = request.user
        try:
            assignment.full_clean()
            assignment.save()
        except ValidationError as exc:
            for field, errors in exc.message_dict.items():
                for error in errors:
                    form.add_error(field, error)
        else:
            log_action('ASSIGNMENT_CREATE', request.user, {'assignment_id': assignment.pk, 'quiz_id': quiz.pk})
            messages.success(request, 'Quiz asignado al curso.')
            return redirect('assignment_list')
    return render(request, 'evaluaciones/assignment_form.html', {'form': form, 'quiz': quiz})


@role_required('DOCENTE')
def assignment_list(request):
    assignments = list(
        Asignacion.objects.filter(quiz__course__teachers__teacher=request.user)
        .select_related('quiz', 'quiz__course')
        .distinct()
        .order_by('-creado_en')
    )
    for assignment in assignments:
        enrolled = Enrollment.objects.filter(course=assignment.quiz.course, estado=Enrollment.APROBADA).count()
        sent = assignment.intentos.filter(estado=Intento.ENVIADO).values('estudiante_id').distinct().count()
        notes = list(assignment.intentos.filter(estado=Intento.ENVIADO).values_list('nota', flat=True))
        assignment.inscritos_count = enrolled
        assignment.participacion = sent
        assignment.promedio = round(sum(notes) / len(notes), 2) if notes else None
    return render(request, 'evaluaciones/assignment_list.html', {'assignments': assignments})


@role_required('DOCENTE')
def assignment_results(request, assignment_id):
    assignment = _assignment_for_teacher(assignment_id, request.user)
    cerrar_intentos_vencidos(assignment)
    enrollments = Enrollment.objects.filter(
        course=assignment.quiz.course,
        estado=Enrollment.APROBADA,
    ).select_related('student')
    rows = []
    for enrollment in enrollments:
        attempts = list(assignment.intentos.filter(estudiante=enrollment.student).order_by('numero'))
        best = nota_final(assignment, enrollment.student)
        progress = next((attempt for attempt in attempts if attempt.estado == Intento.EN_PROGRESO), None)
        rows.append({
            'student': enrollment.student,
            'estado': 'ENVIADO' if best else ('EN_PROGRESO' if progress else 'SIN_INICIAR'),
            'intentos': len(attempts),
            'mejor': best,
            'ultimo_envio': best.enviado_en if best else None,
        })
    question_stats = []
    for question in assignment.quiz.questions.prefetch_related('options').all():
        sent_attempts = [row['mejor'] for row in rows if row['mejor']]
        answers = question.respuestas_intento.filter(intento__in=sent_attempts).select_related('option')
        correct = sum(answer.es_correcta for answer in answers)
        question_stats.append({'question': question, 'correctas': correct, 'total': len(sent_attempts), 'answers': answers})
    return render(request, 'evaluaciones/assignment_results.html', {
        'assignment': assignment,
        'rows': rows,
        'question_stats': question_stats,
    })


@role_required('DOCENTE')
@require_POST
def assignment_close(request, assignment_id):
    assignment = _assignment_for_teacher(assignment_id, request.user)
    assignment.cerrada_manualmente = True
    assignment.save(update_fields=['cerrada_manualmente'])
    cerrar_intentos_vencidos(assignment)
    log_action('ASSIGNMENT_CLOSE', request.user, {'assignment_id': assignment.pk})
    messages.success(request, 'Asignación cerrada.')
    return redirect('assignment_results', assignment_id=assignment.pk)


@role_required('DOCENTE')
@require_POST
def assignment_extend(request, assignment_id):
    assignment = _assignment_for_teacher(assignment_id, request.user)
    value = request.POST.get('cierra_en', '')
    new_close = parse_datetime(value)
    if new_close and timezone.is_naive(new_close):
        new_close = timezone.make_aware(new_close)
    if new_close and new_close > assignment.cierra_en:
        assignment.cierra_en = new_close
        assignment.cerrada_manualmente = False
        assignment.save(update_fields=['cierra_en', 'cerrada_manualmente'])
        log_action('ASSIGNMENT_EXTEND', request.user, {'assignment_id': assignment.pk})
        messages.success(request, 'Fecha de cierre ampliada.')
    else:
        messages.error(request, 'La nueva fecha debe ser posterior al cierre actual.')
    return redirect('assignment_results', assignment_id=assignment.pk)


@role_required('DOCENTE')
@require_POST
def assignment_delete(request, assignment_id):
    assignment = _assignment_for_teacher(assignment_id, request.user)
    if assignment.intentos.exists():
        messages.error(request, 'No se puede eliminar una asignación con intentos.')
    else:
        assignment.delete()
        log_action('ASSIGNMENT_DELETE', request.user, {'assignment_id': assignment_id})
        messages.success(request, 'Asignación eliminada.')
    return redirect('assignment_list')


@role_required('ESTUDIANTE')
@require_POST
def start_attempt(request, assignment_id):
    assignment = get_object_or_404(Asignacion.objects.select_related('quiz'), pk=assignment_id)
    try:
        attempt = iniciar_intento(assignment, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect('estudiante_dashboard')
    return redirect('attempt_view', intento_id=attempt.pk)


def _student_attempt(attempt_id, student):
    return get_object_or_404(
        Intento.objects.select_related('asignacion__quiz'),
        pk=attempt_id,
        estudiante=student,
    )


@role_required('ESTUDIANTE')
def attempt_view(request, intento_id):
    attempt = _student_attempt(intento_id, request.user)
    cerrar_intentos_vencidos(attempt.asignacion)
    attempt.refresh_from_db()
    questions = attempt.asignacion.quiz.questions.prefetch_related('options').all()
    answered = {answer.question_id: answer.option_id for answer in attempt.respuestas.all()}
    return render(request, 'evaluaciones/attempt.html', {
        'attempt': attempt,
        'questions': questions,
        'answered': answered,
    })


@role_required('ESTUDIANTE')
@require_POST
def answer_attempt(request, intento_id):
    attempt = _student_attempt(intento_id, request.user)
    try:
        data = json.loads(request.body or '{}')
        question = get_object_or_404(Question, pk=data.get('question_id'))
        option_id = data.get('option_id')
        option = get_object_or_404(Option, pk=option_id) if option_id is not None else None
        guardar_respuesta(attempt, question, option)
    except (json.JSONDecodeError, ValidationError) as exc:
        message = exc.messages[0] if isinstance(exc, ValidationError) else 'JSON inválido.'
        return JsonResponse({'error': message}, status=400)
    return JsonResponse({'ok': True})


@role_required('ESTUDIANTE')
@require_POST
def submit_attempt(request, intento_id):
    attempt = _student_attempt(intento_id, request.user)
    cerrar_intentos_vencidos(attempt.asignacion)
    attempt.refresh_from_db()
    if attempt.estado == Intento.EN_PROGRESO:
        enviar_intento(attempt)
    return redirect('attempt_review', intento_id=attempt.pk)


@role_required('ESTUDIANTE')
def attempt_review(request, intento_id):
    attempt = _student_attempt(intento_id, request.user)
    cerrar_intentos_vencidos(attempt.asignacion)
    attempt.refresh_from_db()
    answers = attempt.respuestas.select_related('question', 'option').order_by('question__orden')
    return render(request, 'evaluaciones/attempt_review.html', {
        'attempt': attempt,
        'answers': answers if puede_ver_respuestas(attempt) else [],
        'show_answers': puede_ver_respuestas(attempt),
    })
