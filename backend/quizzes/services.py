from .models import Option, Question


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
    # Validar que todos los IDs pertenecen al quiz
    expected_ids = set(quiz.questions.values_list('id', flat=True))
    received_ids = set(question_order)
    
    if expected_ids != received_ids:
        return {'success': False, 'message': 'IDs de preguntas inválidos.'}
    
    # Actualizar orden
    for new_position, question_id in enumerate(question_order, start=1):
        Question.objects.filter(id=question_id, quiz=quiz).update(orden=new_position)
    
    return {'success': True, 'message': 'Preguntas reordenadas exitosamente.'}
