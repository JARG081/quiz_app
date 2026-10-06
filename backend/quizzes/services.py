import hashlib
import json

from django.db import transaction
from django.utils import timezone

from .models import Option, Question, Quiz, TeacherVerificationAnswer, TeacherVerificationAttempt


def compute_quiz_hash(quiz):
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
    payload = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def quiz_is_verified(quiz):
    return bool(quiz.hash_verificado and quiz.hash_verificado == compute_quiz_hash(quiz))


def validate_quiz_content(quiz):
    errors = []
    total = quiz.total_preguntas()
    if not 5 <= total <= 20:
        errors.append(f'El quiz necesita entre 5 y 20 preguntas. Tiene {total}.')
    for question in quiz.questions.prefetch_related('options'):
        options = list(question.options.all())
        if len(options) not in [2, 4]:
            errors.append(f'La pregunta "{question.enunciado[:40]}" no tiene una cantidad válida de opciones.')
        if sum(option.es_correcta for option in options) != 1:
            errors.append(f'La pregunta "{question.enunciado[:40]}" debe tener exactamente 1 opción correcta.')
    return errors


def validate_quiz_publishable(quiz):
    errors = validate_quiz_content(quiz)
    if not quiz_is_verified(quiz):
        errors.append('El quiz debe estar verificado por el docente antes de publicarse.')
    return errors


def grade_verification(quiz, docente, answers):
    with transaction.atomic():
        attempt = TeacherVerificationAttempt.objects.create(
            quiz=quiz,
            docente=docente,
            total=quiz.questions.count(),
            hash_contenido=compute_quiz_hash(quiz),
        )
        correctas = 0
        for question in quiz.questions.prefetch_related('options').all():
            option_id = answers.get(str(question.pk), answers.get(question.pk))
            option = question.options.filter(pk=option_id).first() if option_id else None
            TeacherVerificationAnswer.objects.create(attempt=attempt, question=question, option_marcada=option)
            if option and option.es_correcta:
                correctas += 1
        attempt.correctas = correctas
        attempt.aprobado = correctas == attempt.total and attempt.total > 0
        attempt.finalizado_en = timezone.now()
        attempt.save(update_fields=['correctas', 'aprobado', 'finalizado_en'])
        return attempt


def assert_quiz_editable(quiz):
    if quiz.tiene_asignaciones():
        return False, 'Este quiz ya fue asignado. Duplícalo para modificarlo.'
    if quiz.publicado:
        quiz.publicado = False
        quiz.save(update_fields=['publicado'])
        return True, 'El quiz se despublicó porque cambió su contenido. Verifícalo y publícalo de nuevo.'
    return True, ''


def duplicate_quiz(quiz, user):
    duplicate = Quiz.objects.create(
        titulo=f'{quiz.titulo} (copia)',
        descripcion=quiz.descripcion,
        course=quiz.course,
        creado_por=user,
        publicado=False,
        hash_verificado=quiz.hash_verificado,
        verificado_en=quiz.verificado_en,
    )
    for question in quiz.questions.all().order_by('orden'):
        new_question = Question.objects.create(
            quiz=duplicate,
            enunciado=question.enunciado,
            imagen=question.imagen.name if question.imagen else None,
            explicacion=question.explicacion,
            explicacion_imagen=question.explicacion_imagen.name if question.explicacion_imagen else None,
            orden=question.orden,
        )
        for option in question.options.all().order_by('letra'):
            Option.objects.create(
                question=new_question,
                texto=option.texto,
                letra=option.letra,
                es_correcta=option.es_correcta,
            )
    return duplicate


def question_texts_from_post(post_data, is_vf):
    if is_vf:
        return {'A': 'Verdadero', 'B': 'Falso'}

    return {
        'A': post_data.get('opt_A', '').strip(),
        'B': post_data.get('opt_B', '').strip(),
        'C': post_data.get('opt_C', '').strip(),
        'D': post_data.get('opt_D', '').strip(),
    }


def validate_question_options(texts, correct_letter):
    if len(texts) == 2:
        if correct_letter not in ['A', 'B']:
            return 'Debes seleccionar una opción correcta.'
        return None

    if len(texts) == 4:
        if not all(texts.values()):
            return 'Todas las 4 opciones deben tener texto.'
        if len(set(texts.values())) < 4:
            return 'No puedes tener opciones con textos repetidos.'
        if correct_letter not in ['A', 'B', 'C', 'D']:
            return 'Debes seleccionar la opción correcta.'
        return None

    return 'Formato de pregunta inválido.'


def sync_question_options(question, texts, correct_letter):
    existing_letters = set(question.options.values_list('letra', flat=True))
    incoming_letters = set(texts.keys())

    for letter in existing_letters - incoming_letters:
        Option.objects.filter(question=question, letra=letter).delete()

    for letter, text in texts.items():
        option, _created = Option.objects.get_or_create(question=question, letra=letter)
        option.texto = text
        option.es_correcta = letter == correct_letter
        option.save()


def reorder_questions(quiz, question_order):
    """
    Actualiza el orden de las preguntas en un quiz.
    
    Args:
        quiz: Instancia de Quiz
        question_order: Lista de question IDs en el nuevo orden (ej: [3, 1, 2])
    
    Returns:
        dict con status y mensaje: {'success': True/False, 'message': str}
    """
    editable, message = assert_quiz_editable(quiz)
    if not editable:
        return {'success': False, 'message': message}

    # Validar que todos los IDs pertenecen al quiz
    expected_ids = set(quiz.questions.values_list('id', flat=True))
    received_ids = set(question_order)
    
    if expected_ids != received_ids:
        return {'success': False, 'message': 'IDs de preguntas inválidos.'}
    
    # Actualizar orden
    for new_position, question_id in enumerate(question_order, start=1):
        Question.objects.filter(id=question_id, quiz=quiz).update(orden=new_position)
    
    return {'success': True, 'message': 'Preguntas reordenadas exitosamente.'}
