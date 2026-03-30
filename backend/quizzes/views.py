from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from users.views import role_required
from courses.models import CourseTeacher, Course
from .models import Quiz, Question, Option


def get_docente_courses(user):
    return [ct.course for ct in CourseTeacher.objects.filter(teacher=user).select_related('course')]


@role_required('DOCENTE')
def quiz_list(request):
    mis_cursos = get_docente_courses(request.user)
    quizzes = Quiz.objects.filter(course__in=mis_cursos).select_related('course')
    return render(request, 'quizzes/quiz_list.html', {'quizzes': quizzes})


@role_required('DOCENTE')
def quiz_create(request):
    mis_cursos = get_docente_courses(request.user)
    if request.method == 'POST':
        titulo = request.POST.get('titulo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        course_id = request.POST.get('course')
        tiempo = request.POST.get('tiempo_por_pregunta', 30)

        course = get_object_or_404(Course, pk=course_id)
        if course not in mis_cursos:
            messages.error(request, 'No tienes acceso a ese curso.')
            return redirect('quiz_list')

        if not titulo:
            messages.error(request, 'El título es obligatorio.')
        else:
            quiz = Quiz.objects.create(
                titulo=titulo, descripcion=descripcion,
                course=course, creado_por=request.user,
                tiempo_por_pregunta=int(tiempo)
            )
            messages.success(request, 'Quiz creado. Ahora agrega preguntas.')
            return redirect('quiz_builder', quiz_id=quiz.pk)

    return render(request, 'quizzes/quiz_form.html', {'mis_cursos': mis_cursos, 'action': 'Crear'})


@role_required('DOCENTE')
def quiz_edit(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    mis_cursos = get_docente_courses(request.user)
    if request.method == 'POST':
        quiz.titulo = request.POST.get('titulo', quiz.titulo).strip()
        quiz.descripcion = request.POST.get('descripcion', quiz.descripcion).strip()
        quiz.tiempo_por_pregunta = int(request.POST.get('tiempo_por_pregunta', quiz.tiempo_por_pregunta))
        quiz.save()
        messages.success(request, 'Quiz actualizado.')
        return redirect('quiz_builder', quiz_id=quiz.pk)
    return render(request, 'quizzes/quiz_form.html', {'quiz': quiz, 'mis_cursos': mis_cursos, 'action': 'Editar'})


@role_required('DOCENTE')
def quiz_delete(request, quiz_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    if request.method == 'POST':
        quiz.delete()
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
        # Validate each question has 4 options and 1 correct
        for q in quiz.questions.prefetch_related('options'):
            opts = list(q.options.all())
            if len(opts) != 4:
                messages.error(request, f'La pregunta "{q.enunciado[:40]}" no tiene exactamente 4 opciones.')
                return redirect('quiz_builder', quiz_id=quiz_id)
            if sum(1 for o in opts if o.es_correcta) != 1:
                messages.error(request, f'La pregunta "{q.enunciado[:40]}" debe tener exactamente 1 opción correcta.')
                return redirect('quiz_builder', quiz_id=quiz_id)
        quiz.publicado = True
        messages.success(request, 'Quiz publicado exitosamente.')
    else:
        quiz.publicado = False
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
        if not enunciado:
            messages.error(request, 'El enunciado es obligatorio.')
        else:
            orden = quiz.total_preguntas() + 1
            question = Question.objects.create(quiz=quiz, enunciado=enunciado, orden=orden)
            # Create 4 empty options
            for letra in ['A', 'B', 'C', 'D']:
                Option.objects.create(question=question, texto='', letra=letra, es_correcta=False)
            messages.success(request, 'Pregunta agregada. Completa las opciones.')
            return redirect('quiz_builder', quiz_id=quiz_id)

    return render(request, 'quizzes/question_form.html', {'quiz': quiz})


@role_required('DOCENTE')
def edit_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    question = get_object_or_404(Question, pk=question_id, quiz=quiz)
    options = list(question.options.order_by('letra'))

    if request.method == 'POST':
        enunciado = request.POST.get('enunciado', '').strip()
        correcta = request.POST.get('correcta', '')

        if not enunciado:
            messages.error(request, 'El enunciado es obligatorio.')
        else:
            question.enunciado = enunciado
            question.save()

            textos = {'A': request.POST.get('texto_A',''), 'B': request.POST.get('texto_B',''),
                      'C': request.POST.get('texto_C',''), 'D': request.POST.get('texto_D','')}

            # Validate
            if not all(textos.values()):
                messages.error(request, 'Todas las opciones deben tener texto.')
                return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})
            if correcta not in ['A', 'B', 'C', 'D']:
                messages.error(request, 'Debes seleccionar una opción correcta.')
                return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})

            for opt in options:
                opt.texto = textos[opt.letra]
                opt.es_correcta = (opt.letra == correcta)
                opt.save()

            messages.success(request, 'Pregunta actualizada.')
            return redirect('quiz_builder', quiz_id=quiz_id)

    return render(request, 'quizzes/edit_question.html', {'quiz': quiz, 'question': question, 'options': options})


@role_required('DOCENTE')
def delete_question(request, quiz_id, question_id):
    quiz = get_object_or_404(Quiz, pk=quiz_id, creado_por=request.user)
    question = get_object_or_404(Question, pk=question_id, quiz=quiz)
    if request.method == 'POST':
        question.delete()
        # Re-order remaining questions
        for i, q in enumerate(quiz.questions.order_by('orden'), start=1):
            q.orden = i
            q.save()
        messages.success(request, 'Pregunta eliminada.')
    return redirect('quiz_builder', quiz_id=quiz_id)
