from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
import json
from users.views import role_required
from courses.models import CourseTeacher, Course
from .models import Quiz, Question, Option, TeacherVerificationAttempt
from .forms import QuizForm
from .services import (
    assert_quiz_editable,
    duplicate_quiz,
    compute_quiz_hash,
    grade_verification,
    quiz_is_verified,
    validate_quiz_content,
    validate_quiz_publishable,
    question_texts_from_post,
    validate_question_options,
    sync_question_options,
    reorder_questions,
)
from quiz_platform.audit import log_action



def get_docente_courses(user):
    return [ct.course for ct in CourseTeacher.objects.filter(teacher=user).select_related('course')]


@role_required('DOCENTE')
def quiz_list(request):
    from collections import defaultdict
    
    mis_cursos = get_docente_courses(request.user)
    
    course_filter = request.GET.get('course')
    if course_filter:
        quizzes = Quiz.objects.filter(course__in=mis_cursos, course_id=course_filter).select_related('course')
    else:
        quizzes = Quiz.objects.filter(course__in=mis_cursos).select_related('course')
        
    courses_dict = defaultdict(list)
    for q in quizzes:
        courses_dict[q.course].append(q)
        
    return render(request, 'quizzes/quiz_list.html', {
        'courses_dict': dict(courses_dict),
        'mis_cursos': mis_cursos
    })


@role_required('DOCENTE')
def quiz_create(request):
    mis_cursos = get_docente_courses(request.user)
    form = QuizForm(course_queryset=Course.objects.filter(pk__in=[c.pk for c in mis_cursos]))

    if request.method == 'POST':
        form = QuizForm(
            request.POST,
            course_queryset=Course.objects.filter(pk__in=[c.pk for c in mis_cursos])
        )
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.creado_por = request.user
            quiz.save()
            
            log_action('QUIZ_CREATE', request.user, {
                'quiz_id': quiz.pk,
                'titulo': quiz.titulo,
                'course': quiz.course.nombre,
            })
            
            messages.success(request, 'Quiz creado. Ahora agrega preguntas.')
            return redirect('quiz_builder', quiz_id=quiz.pk)

    return render(request, 'quizzes/quiz_form.html', {'mis_cursos': mis_cursos, 'action': 'Crear', 'form': form})


@role_required('DOCENTE')
def quiz_edit(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if quiz.tiene_asignaciones():
        messages.error(request, 'Este quiz ya fue asignado. Duplícalo para modificarlo.')
        return redirect('quiz_builder', quiz_id=quiz_id)
    mis_cursos = get_docente_courses(request.user)
    form = QuizForm(instance=quiz, course_queryset=Course.objects.filter(pk__in=[c.pk for c in mis_cursos]), allow_course_change=False)

    if request.method == 'POST':
        form = QuizForm(
            request.POST,
            instance=quiz,
            course_queryset=Course.objects.filter(pk__in=[c.pk for c in mis_cursos]),
            allow_course_change=False,
        )
        if form.is_valid():
            form.save()
            log_action('QUIZ_EDIT', request.user, {'quiz_id': quiz.pk, 'titulo': quiz.titulo})
            messages.success(request, 'Quiz actualizado.')
            return redirect('quiz_builder', quiz_id=quiz.pk)
    return render(request, 'quizzes/quiz_form.html', {'quiz': quiz, 'mis_cursos': mis_cursos, 'action': 'Editar', 'form': form})


@role_required('DOCENTE')
def quiz_delete(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if request.method == 'POST':
        quiz_data = {'quiz_id': quiz.pk, 'titulo': quiz.titulo}
        quiz.delete()
        log_action('QUIZ_DELETE', request.user, quiz_data)
        messages.success(request, 'Quiz eliminado.')
        return redirect('quiz_list')
    return render(request, 'quizzes/quiz_confirm_delete.html', {'quiz': quiz})


@role_required('DOCENTE')
def quiz_builder(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    questions = quiz.questions.prefetch_related('options').all()
    return render(request, 'quizzes/quiz_builder.html', {
        'quiz': quiz,
        'questions': questions,
        'total': questions.count(),
        'can_publish': quiz.can_publish(),
        'tiene_asignaciones': quiz.tiene_asignaciones(),
        'verificado': quiz_is_verified(quiz),
    })


@role_required('DOCENTE')
@require_POST
def duplicate_quiz_view(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    duplicate = duplicate_quiz(quiz, request.user)
    log_action('QUIZ_DUPLICATE', request.user, {'quiz_id': quiz.pk, 'duplicate_id': duplicate.pk})
    messages.success(request, 'Quiz duplicado. Puedes modificar la copia.')
    return redirect('quiz_builder', quiz_id=duplicate.pk)


@role_required('DOCENTE')
@require_POST
def toggle_publish(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if not quiz.publicado:
        errors = validate_quiz_publishable(quiz)
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('quiz_builder', quiz_id=quiz_id)
        quiz.publicado = True
        log_action('QUIZ_PUBLISH', request.user, {'quiz_id': quiz.pk, 'titulo': quiz.titulo})
        messages.success(request, 'Quiz publicado exitosamente.')
    else:
        quiz.publicado = False
        log_action('QUIZ_UNPUBLISH', request.user, {'quiz_id': quiz.pk, 'titulo': quiz.titulo})
        messages.success(request, 'Quiz despublicado.')
    quiz.save()
    return redirect('quiz_builder', quiz_id=quiz_id)


@role_required('DOCENTE')
def verify_quiz(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    errors = validate_quiz_content(quiz)
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('quiz_builder', quiz_id=quiz_id)
    questions = quiz.questions.prefetch_related('options').all()
    if request.method == 'POST':
        attempt = grade_verification(
            quiz,
            request.user,
            {key.removeprefix('question_'): value for key, value in request.POST.items() if key.startswith('question_')},
        )
        return redirect('verify_result', quiz_id=quiz.pk, attempt_id=attempt.pk)
    return render(request, 'quizzes/verify_quiz.html', {'quiz': quiz, 'questions': questions})


@role_required('DOCENTE')
def verify_result(request, quiz_id, attempt_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    attempt = get_object_or_404(
        TeacherVerificationAttempt.objects.select_related('quiz').prefetch_related('answers__question', 'answers__option_marcada'),
        pk=attempt_id,
        quiz=quiz,
        docente=request.user,
    )
    if attempt.aprobado and quiz.hash_verificado != compute_quiz_hash(quiz):
        quiz.hash_verificado = attempt.hash_contenido
        quiz.verificado_en = attempt.finalizado_en
        quiz.save(update_fields=['hash_verificado', 'verificado_en'])
        log_action('QUIZ_VERIFY_PASS', request.user, {'quiz_id': quiz.pk, 'attempt_id': attempt.pk})
    elif not attempt.aprobado:
        log_action('QUIZ_VERIFY_FAIL', request.user, {'quiz_id': quiz.pk, 'attempt_id': attempt.pk})
    return render(request, 'quizzes/verify_result.html', {'quiz': quiz, 'attempt': attempt})


# ─── Questions ───────────────────────────────────────────────────────────────

@role_required('DOCENTE')
def add_question(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if request.method == 'POST':
        editable, message = assert_quiz_editable(quiz)
        if not editable:
            messages.error(request, message)
            return redirect('quiz_builder', quiz_id=quiz_id)
        if message:
            messages.warning(request, message)
    if quiz.total_preguntas() >= 20:
        messages.error(request, 'Máximo 20 preguntas por quiz.')
        return redirect('quiz_builder', quiz_id=quiz_id)

    if request.method == 'POST':
        enunciado = request.POST.get('enunciado', '').strip()
        es_vf = request.POST.get('es_vf') == 'on'
        correcta = request.POST.get('correcta', 'A')
        textos = question_texts_from_post(request.POST, es_vf)

        if not enunciado:
            messages.error(request, 'El enunciado es obligatorio.')
            return redirect('quiz_builder', quiz_id=quiz_id)

        validation_error = validate_question_options(textos, correcta)
        if validation_error:
            messages.error(request, validation_error)
            return redirect('quiz_builder', quiz_id=quiz_id)

        if es_vf and correcta not in ['A', 'B']:
            correcta = 'A'

        orden = quiz.total_preguntas() + 1
        question = Question.objects.create(quiz=quiz, enunciado=enunciado, orden=orden)
        if request.FILES.get('imagen'):
            question.imagen = request.FILES['imagen']
        question.explicacion = request.POST.get('explicacion', '').strip()
        if request.FILES.get('explicacion_imagen'):
            question.explicacion_imagen = request.FILES['explicacion_imagen']
        question.save()

        sync_question_options(question, textos, correcta)
        
        log_action('QUESTION_CREATE', request.user, {
            'quiz_id': quiz.pk,
            'question_id': question.pk,
            'tipo': 'VF' if es_vf else 'MC',
        })

        messages.success(request, 'Pregunta guardada exitosamente.')
        return redirect('quiz_builder', quiz_id=quiz_id)

    return render(request, 'quizzes/question_form.html', {'quiz': quiz})


@role_required('DOCENTE')
def edit_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    question = get_object_or_404(Question, pk=question_id, quiz=quiz)
    options = list(question.options.order_by('letra'))

    if request.method == 'POST':
        editable, message = assert_quiz_editable(quiz)
        if not editable:
            messages.error(request, message)
            return redirect('quiz_builder', quiz_id=quiz_id)
        if message:
            messages.warning(request, message)
        enunciado = request.POST.get('enunciado', '').strip()
        es_vf = len(options) == 2 or request.POST.get('es_vf') == 'on' 
        correcta = request.POST.get('correcta', '')
        textos = question_texts_from_post(request.POST, es_vf)

        if not enunciado:
            messages.error(request, 'El enunciado es obligatorio.')
            return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})

        validation_error = validate_question_options(textos, correcta)
        if validation_error:
            messages.error(request, validation_error)
            return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})

        question.enunciado = enunciado
        question.explicacion = request.POST.get('explicacion', '').strip()
        if request.FILES.get('imagen'):
            question.imagen = request.FILES['imagen']
        if request.FILES.get('explicacion_imagen'):
            question.explicacion_imagen = request.FILES['explicacion_imagen']
        question.save()

        if es_vf and correcta not in ['A', 'B']:
            correcta = 'A'

        sync_question_options(question, textos, correcta)

        log_action('QUESTION_EDIT', request.user, {'quiz_id': quiz.pk, 'question_id': question.pk})
        messages.success(request, 'Pregunta actualizada.')
        return redirect('quiz_builder', quiz_id=quiz_id)

    return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})


@role_required('DOCENTE')
def delete_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    question = get_object_or_404(Question, pk=question_id, quiz=quiz)
    if request.method == 'POST':
        editable, message = assert_quiz_editable(quiz)
        if not editable:
            messages.error(request, message)
            return redirect('quiz_builder', quiz_id=quiz_id)
        if message:
            messages.warning(request, message)
        question_data = {'quiz_id': quiz.pk, 'question_id': question.pk}
        question.delete()
        log_action('QUESTION_DELETE', request.user, question_data)
        # Re-order remaining questions
        for i, q in enumerate(quiz.questions.order_by('orden'), start=1):
            q.orden = i
            q.save()
        messages.success(request, 'Pregunta eliminada.')
    return redirect('quiz_builder', quiz_id=quiz_id)


@role_required('DOCENTE')
@require_http_methods(['POST'])
def reorder_questions_api(request, quiz_id):
    """API endpoint para reordenar preguntas vía drag-drop."""
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)

    try:
        data = json.loads(request.body)
        question_order = data.get('order', [])
        
        result = reorder_questions(quiz, question_order)
        
        if result['success']:
            log_action('QUESTION_REORDER', request.user, {'quiz_id': quiz.pk})
            return JsonResponse({'success': True, 'message': result['message']}, status=200)
        else:
            return JsonResponse({'success': False, 'message': result['message']}, status=400)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'Formato JSON inválido.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)
