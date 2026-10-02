from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
import json
from users.views import role_required
from courses.models import CourseTeacher, Course
from .models import Quiz, Question, Option
from .forms import QuizForm
from .services import question_texts_from_post, validate_question_options, sync_question_options, reorder_questions
from quiz_platform.audit import log_action



def get_docente_courses(user):
    return [ct.course for ct in CourseTeacher.objects.filter(teacher=user).select_related('course')]


@role_required('DOCENTE')
def quiz_list(request):
    from collections import defaultdict
    from sessions_app.services import active_session_for_teacher
    
    mis_cursos = get_docente_courses(request.user)
    
    course_filter = request.GET.get('course')
    if course_filter:
        quizzes = Quiz.objects.filter(course__in=mis_cursos, course_id=course_filter).select_related('course')
    else:
        quizzes = Quiz.objects.filter(course__in=mis_cursos).select_related('course')
        
    courses_dict = defaultdict(list)
    for q in quizzes:
        courses_dict[q.course].append(q)
        
    active_session = active_session_for_teacher(request.user)

    return render(request, 'quizzes/quiz_list.html', {
        'courses_dict': dict(courses_dict),
        'active_session': active_session,
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
    })


@role_required('DOCENTE')
def toggle_publish(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if not quiz.publicado:
        if not quiz.can_publish():
            messages.error(request, f'El quiz necesita entre 5 y 20 preguntas. Tiene {quiz.total_preguntas()}.')
            return redirect('quiz_builder', quiz_id=quiz_id)
        # Validate each question has 2 or 4 options and 1 correct
        for q in quiz.questions.prefetch_related('options'):
            opts = list(q.options.all())
            if len(opts) not in [2, 4]:
                messages.error(request, f'La pregunta "{q.enunciado[:40]}" no tiene una cantidad válida de opciones.')
                return redirect('quiz_builder', quiz_id=quiz_id)
            if sum(1 for o in opts if o.es_correcta) != 1:
                messages.error(request, f'La pregunta "{q.enunciado[:40]}" debe tener exactamente 1 opción correcta.')
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


# ─── Questions ───────────────────────────────────────────────────────────────

@role_required('DOCENTE')
def add_question(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
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

        messages.success(request, 'Pregunta actualizada.')
        return redirect('quiz_builder', quiz_id=quiz_id)

    return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})


@role_required('DOCENTE')
def delete_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    question = get_object_or_404(Question, pk=question_id, quiz=quiz)
    if request.method == 'POST':
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
