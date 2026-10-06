import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from courses.models import Enrollment
from quiz_platform.audit import log_action
from quizzes.models import Question

from .models import Asignacion, Intento, RespuestaIntento

GRACE_PERIOD = timedelta(seconds=30)


def compute_content_hash(quiz):
    content = []
    for question in quiz.questions.all().order_by('orden'):
        content.append({
            'orden': question.orden,
            'enunciado': question.enunciado,
            'opciones': [
                {'letra': option.letra, 'texto': option.texto, 'es_correcta': option.es_correcta}
                for option in question.options.all().order_by('letra')
            ],
        })
    encoded = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _esta_inscrito(estudiante, asignacion):
    return Enrollment.objects.filter(
        course=asignacion.quiz.course,
        student=estudiante,
        estado=Enrollment.APROBADA,
    ).exists()


def asignaciones_disponibles(estudiante):
    now = timezone.now()
    return Asignacion.objects.filter(
        quiz__publicado=True,
        quiz__course__enrollments__student=estudiante,
        quiz__course__enrollments__estado=Enrollment.APROBADA,
        abre_en__lte=now,
        cierra_en__gt=now,
        cerrada_manualmente=False,
        modo=Asignacion.NORMAL,
    ).select_related('quiz', 'quiz__course').distinct()


def iniciar_intento(asignacion, estudiante):
    if not _esta_inscrito(estudiante, asignacion):
        raise ValidationError('No estás inscrito en el curso de esta asignación.')
    if not asignacion.esta_abierta():
        raise ValidationError('La asignación no está abierta.')

    with transaction.atomic():
        locked = Asignacion.objects.select_for_update().select_related('quiz').get(pk=asignacion.pk)
        current = locked.intentos.filter(estudiante=estudiante, estado=Intento.EN_PROGRESO).first()
        if current:
            return current
        used = locked.intentos.filter(estudiante=estudiante).count()
        if used >= locked.intentos_permitidos:
            raise ValidationError('Ya usaste todos los intentos permitidos.')
        now = timezone.now()
        limit = None
        if locked.tiempo_limite_minutos:
            limit = min(now + timedelta(minutes=locked.tiempo_limite_minutos), locked.cierra_en)
        return Intento.objects.create(
            asignacion=locked,
            estudiante=estudiante,
            numero=used + 1,
            limite_en=limit,
            hash_contenido=compute_content_hash(locked.quiz),
            total=locked.quiz.questions.count(),
        )


def guardar_respuesta(intento, question, option):
    if intento.estado != Intento.EN_PROGRESO:
        raise ValidationError('El intento ya fue enviado.')
    if intento.limite_en and timezone.now() > intento.limite_en + GRACE_PERIOD:
        raise ValidationError('El tiempo del intento ha terminado.')
    if question.quiz_id != intento.asignacion.quiz_id:
        raise ValidationError('La pregunta no pertenece a este quiz.')
    if option is not None and option.question_id != question.pk:
        raise ValidationError('La opción no pertenece a esta pregunta.')
    answer, _ = RespuestaIntento.objects.update_or_create(
        intento=intento,
        question=question,
        defaults={'option': option, 'es_correcta': False},
    )
    return answer


def enviar_intento(intento, automatico=False):
    if intento.estado == Intento.ENVIADO:
        return intento
    questions = list(intento.asignacion.quiz.questions.all())
    answers = {
        answer.question_id: answer
        for answer in intento.respuestas.select_related('option')
    }
    correctas = 0
    for question in questions:
        answer = answers.get(question.pk)
        is_correct = bool(answer and answer.option_id and answer.option.es_correcta)
        if answer:
            answer.es_correcta = is_correct
            answer.save(update_fields=['es_correcta'])
        if is_correct:
            correctas += 1
    total = len(questions)
    nota = (Decimal(correctas) * Decimal('100') / Decimal(total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if total else Decimal('0.00')
    intento.estado = Intento.ENVIADO
    intento.enviado_en = timezone.now()
    intento.enviado_automaticamente = automatico
    intento.correctas = correctas
    intento.total = total
    intento.nota = nota
    intento.save(update_fields=['estado', 'enviado_en', 'enviado_automaticamente', 'correctas', 'total', 'nota'])
    log_action('ATTEMPT_SUBMIT', intento.estudiante, {
        'intento_id': intento.pk,
        'automatico': automatico,
        'nota': intento.nota,
    })
    return intento


def cerrar_intentos_vencidos(asignacion=None):
    now = timezone.now()
    attempts = Intento.objects.filter(estado=Intento.EN_PROGRESO, limite_en__isnull=False, limite_en__lt=now - GRACE_PERIOD)
    if asignacion is not None:
        attempts = attempts.filter(asignacion=asignacion)
    total = attempts.count()
    for intento in attempts.select_related('asignacion__quiz'):
        enviar_intento(intento, automatico=True)
    return total


def nota_final(asignacion, estudiante):
    return asignacion.intentos.filter(
        estudiante=estudiante,
        estado=Intento.ENVIADO,
    ).order_by('-nota', 'enviado_en', 'id').first()


def puede_ver_respuestas(intento):
    assignment = Asignacion.objects.get(pk=intento.asignacion_id)
    if assignment.mostrar_respuestas == Asignacion.NUNCA:
        return False
    if assignment.mostrar_respuestas == Asignacion.AL_ENVIAR:
        return intento.estado == Intento.ENVIADO
    return intento.estado == Intento.ENVIADO and not assignment.esta_abierta()
