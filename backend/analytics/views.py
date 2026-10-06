from collections import defaultdict
from io import BytesIO

from django.contrib.auth.models import User
from django.db.models import Count, Max, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from courses.models import Course, Enrollment
from evaluaciones.models import Asignacion, Intento, RespuestaIntento
from evaluaciones.services import cerrar_intentos_vencidos
from quizzes.models import Quiz
from users.views import role_required


def _admin_filters(request):
    filters = Q()
    course_id = request.GET.get('course')
    teacher_id = request.GET.get('docente')
    since = request.GET.get('desde')
    until = request.GET.get('hasta')
    if course_id:
        filters &= Q(quiz__course_id=course_id)
    if teacher_id:
        filters &= Q(quiz__course__teachers__teacher_id=teacher_id)
    if since:
        filters &= Q(cierra_en__date__gte=since)
    if until:
        filters &= Q(cierra_en__date__lte=until)
    return filters, course_id, teacher_id, since, until


def _attempt_summaries(attempt_rows):
    best = {}
    sent = defaultdict(set)
    latest = {}
    for row in attempt_rows:
        assignment_id = row['asignacion_id']
        student_id = row['estudiante_id']
        sent[assignment_id].add(student_id)
        submitted = row['enviado_en']
        latest[assignment_id] = max(latest.get(assignment_id, submitted), submitted)
        key = (assignment_id, student_id)
        current = best.get(key)
        if current is None or (-row['nota'], submitted, row['id']) < (-current['nota'], current['enviado_en'], current['id']):
            best[key] = row
    return best, sent, latest


def _best_attempts(attempts):
    best = {}
    for attempt in attempts:
        current = best.get(attempt.estudiante_id)
        if current is None or (-attempt.nota, attempt.enviado_en, attempt.id) < (-current.nota, current.enviado_en, current.id):
            best[attempt.estudiante_id] = attempt
    return best


@role_required('ESTUDIANTE')
def student_stats(request):
    cerrar_intentos_vencidos()
    assignments = Asignacion.objects.filter(
        quiz__course__enrollments__student=request.user,
        quiz__course__enrollments__estado=Enrollment.APROBADA,
    ).select_related('quiz', 'quiz__course').prefetch_related(
        Prefetch(
            'intentos',
            queryset=Intento.objects.filter(estudiante=request.user, estado=Intento.ENVIADO),
            to_attr='student_attempts',
        )
    ).distinct().order_by('-cierra_en')

    quiz_stats = []
    scores = []
    for assignment in assignments:
        attempts = sorted(assignment.student_attempts, key=lambda attempt: (-attempt.nota, attempt.enviado_en, attempt.id))
        if not attempts:
            continue
        attempt = attempts[0]
        scores.append(attempt.nota)
        quiz_stats.append({
            'assignment': assignment,
            'quiz': assignment.quiz,
            'correctas': attempt.correctas,
            'total': attempt.total,
            'score': attempt.nota,
            'submitted_at': attempt.enviado_en,
            'attempt': attempt,
            'width_attr': f'style="width: {attempt.nota}%;"',
        })

    return render(request, 'analytics/student_stats.html', {
        'quiz_stats': quiz_stats,
        'avg_general': round(sum(scores) / len(scores), 2) if scores else 0,
    })


@role_required('DOCENTE')
def docente_stats(request):
    courses = Course.objects.filter(teachers__teacher=request.user).distinct()
    course_id = request.GET.get('course')
    if course_id:
        courses = courses.filter(pk=course_id)

    answer_queryset = RespuestaIntento.objects.select_related('question', 'option')
    attempt_queryset = Intento.objects.filter(estado=Intento.ENVIADO).select_related('estudiante').prefetch_related(
        Prefetch('respuestas', queryset=answer_queryset, to_attr='answer_rows')
    )
    assignments = Asignacion.objects.filter(
        quiz__course__in=courses,
    ).select_related('quiz', 'quiz__course').prefetch_related(
        'quiz__questions__options',
        Prefetch(
            'quiz__course__enrollments',
            queryset=Enrollment.objects.filter(estado=Enrollment.APROBADA),
            to_attr='approved_enrollments',
        ),
        Prefetch('intentos', queryset=attempt_queryset, to_attr='submitted_attempts'),
    ).distinct().order_by('-creado_en')

    quiz_stats = []
    for assignment in assignments:
        enrolled_ids = {enrollment.student_id for enrollment in assignment.quiz.course.approved_enrollments}
        best = {student_id: attempt for student_id, attempt in _best_attempts(assignment.submitted_attempts).items() if student_id in enrolled_ids}
        question_data = []
        for question in assignment.quiz.questions.all():
            answers = [answer for attempt in best.values() for answer in attempt.answer_rows if answer.question_id == question.pk]
            options = []
            for option in question.options.all():
                votes = sum(answer.option_id == option.pk for answer in answers)
                percentage = round(votes / len(answers) * 100, 2) if answers else 0
                options.append({
                    'letra': option.letra,
                    'texto': option.texto,
                    'es_correcta': option.es_correcta,
                    'votos': votes,
                    'porcentaje': percentage,
                    'width_attr': f'style="width: {percentage}%;"',
                })
            question_data.append({
                'enunciado': question.enunciado[:60],
                'opciones': options,
                'correctas': sum(answer.es_correcta for answer in answers),
                'total': len(answers),
            })

        notes = [attempt.nota for attempt in best.values()]
        quiz_stats.append({
            'assignment': assignment,
            'quiz': assignment.quiz,
            'participantes': len(best),
            'inscritos': len(enrolled_ids),
            'avg_score': round(sum(notes) / len(notes), 2) if notes else 0,
            'pregunta_data': question_data,
        })

    return render(request, 'analytics/docente_stats.html', {
        'quiz_stats': quiz_stats,
        'mis_cursos': courses,
        'selected_course': course_id,
    })


def _admin_assignment_data(request):
    assignment_filter, course_id, teacher_id, since, until = _admin_filters(request)
    assignments = list(
        Asignacion.objects.filter(assignment_filter)
        .select_related('quiz', 'quiz__course')
        .order_by('quiz__course__nombre', 'id')
    )
    assignment_ids = [assignment.pk for assignment in assignments]
    attempt_rows = list(Intento.objects.filter(
        asignacion_id__in=assignment_ids,
        estado=Intento.ENVIADO,
    ).values('id', 'asignacion_id', 'estudiante_id', 'nota', 'enviado_en'))
    best, sent, latest = _attempt_summaries(attempt_rows)
    return assignments, best, sent, latest, course_id, teacher_id, since, until


@role_required('ADMIN')
def admin_stats(request):
    cerrar_intentos_vencidos()
    assignments, best, sent, latest, course_id, teacher_id, since, until = _admin_assignment_data(request)
    assignment_ids = {assignment.pk for assignment in assignments}
    assignment_filter = Q(quizzes__asignaciones__in=assignment_ids)
    courses = list(Course.objects.annotate(
        quizzes_count=Count('quizzes', distinct=True),
        assignments_count=Count('quizzes__asignaciones', filter=assignment_filter, distinct=True),
        approved_students_count=Count(
            'enrollments',
            filter=Q(enrollments__estado=Enrollment.APROBADA),
            distinct=True,
        ),
    ).filter(quizzes__asignaciones__in=assignment_ids).distinct()) if assignment_ids else []

    assignment_by_course = defaultdict(list)
    for assignment in assignments:
        assignment_by_course[assignment.quiz.course_id].append(assignment)
    course_stats = []
    for course in courses:
        course_assignments = assignment_by_course[course.pk]
        participation = []
        notes = []
        activity = None
        for assignment in course_assignments:
            enrolled = course.approved_students_count
            participation.append(len(sent[assignment.pk]) / enrolled * 100 if enrolled else 0)
            notes.extend(row['nota'] for (assignment_id, _), row in best.items() if assignment_id == assignment.pk)
            candidate_activity = latest.get(assignment.pk) or assignment.creado_en
            activity = max(activity, candidate_activity) if activity else candidate_activity
        course_stats.append({
            'course': course,
            'quizzes': course.quizzes_count,
            'assignments': len(course_assignments),
            'enrolled': course.approved_students_count,
            'participants': len({student_id for assignment in course_assignments for student_id in sent[assignment.pk]}),
            'participation': round(sum(participation) / len(participation), 2) if participation else 0,
            'average': round(sum(notes) / len(notes), 2) if notes else 0,
            'last_activity': activity,
        })

    final_notes = [row['nota'] for row in best.values()]
    now = timezone.now()
    return render(request, 'analytics/admin_stats.html', {
        'metrics': {
            'courses': Course.objects.count(),
            'teachers': User.objects.filter(profile__role='DOCENTE').count(),
            'students': User.objects.filter(profile__role='ESTUDIANTE').count(),
            'quizzes_draft': Quiz.objects.filter(publicado=False).count(),
            'quizzes_published': Quiz.objects.filter(publicado=True).count(),
            'assignments_open': Asignacion.objects.filter(cerrada_manualmente=False, abre_en__lte=now, cierra_en__gt=now).count(),
            'assignments_closed': Asignacion.objects.filter(Q(cerrada_manualmente=True) | Q(cierra_en__lte=now)).count(),
            'submitted': Intento.objects.filter(estado=Intento.ENVIADO).count(),
            'average': round(sum(final_notes) / len(final_notes), 2) if final_notes else 0,
        },
        'course_stats': course_stats,
        'courses_filter': Course.objects.order_by('nombre'),
        'teachers_filter': User.objects.filter(profile__role='DOCENTE').order_by('username'),
        'selected_course': course_id,
        'selected_teacher': teacher_id,
        'selected_since': since,
        'selected_until': until,
    })


@role_required('ADMIN')
def admin_course_detail(request, course_id):
    course = Course.objects.get(pk=course_id)
    assignments = list(Asignacion.objects.filter(quiz__course=course).select_related('quiz').order_by('-cierra_en'))
    attempt_rows = list(Intento.objects.filter(
        asignacion__in=assignments,
        estado=Intento.ENVIADO,
    ).values('id', 'asignacion_id', 'estudiante_id', 'nota', 'enviado_en'))
    best, sent, latest = _attempt_summaries(attempt_rows)
    assignment_rows = []
    enrolled = Enrollment.objects.filter(course=course, estado=Enrollment.APROBADA).count()
    for assignment in assignments:
        notes = [row['nota'] for (assignment_id, _), row in best.items() if assignment_id == assignment.pk]
        assignment_rows.append({
            'assignment': assignment,
            'participants': len(sent[assignment.pk]),
            'enrolled': enrolled,
            'participation': round(len(sent[assignment.pk]) / enrolled * 100, 2) if enrolled else 0,
            'average': round(sum(notes) / len(notes), 2) if notes else 0,
            'latest': latest.get(assignment.pk),
        })
    best_ids = [row['id'] for row in best.values() if row['asignacion_id'] in {assignment.pk for assignment in assignments}]
    answers = RespuestaIntento.objects.filter(intento_id__in=best_ids).values('question_id', 'es_correcta')
    question_totals = defaultdict(lambda: [0, 0])
    for answer in answers:
        question_totals[answer['question_id']][1] += 1
        question_totals[answer['question_id']][0] += int(answer['es_correcta'])
    questions = list(course.quizzes.prefetch_related('questions').values_list('questions__id', 'questions__enunciado'))
    lowest_questions = sorted((
        {'enunciado': statement, 'question_id': question_id, 'percentage': round(question_totals[question_id][0] / question_totals[question_id][1] * 100, 2) if question_totals[question_id][1] else 0}
        for question_id, statement in questions
    ), key=lambda item: item['percentage'])[:5]
    return render(request, 'analytics/admin_course_detail.html', {
        'course': course,
        'teachers': User.objects.filter(teaching_courses__course=course).distinct(),
        'assignments': assignment_rows,
        'lowest_questions': lowest_questions,
    })


@role_required('ADMIN')
def admin_course_export(request):
    assignments, best, sent, latest, *_ = _admin_assignment_data(request)
    course_ids = {assignment.quiz.course_id for assignment in assignments}
    courses = Course.objects.filter(pk__in=course_ids).annotate(
        quizzes_count=Count('quizzes', distinct=True),
        approved_students_count=Count('enrollments', filter=Q(enrollments__estado=Enrollment.APROBADA), distinct=True),
    )
    from openpyxl import Workbook
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Cursos'
    sheet.append(['Curso', 'Quices', 'Asignaciones', 'Inscritos', 'Participación %', 'Promedio %', 'Última actividad'])
    for course in courses:
        course_assignments = [assignment for assignment in assignments if assignment.quiz.course_id == course.pk]
        participations = [len(sent[assignment.pk]) / course.approved_students_count * 100 if course.approved_students_count else 0 for assignment in course_assignments]
        notes = [row['nota'] for (assignment_id, _), row in best.items() if assignment_id in {assignment.pk for assignment in course_assignments}]
        sheet.append([
            course.nombre,
            course.quizzes_count,
            len(course_assignments),
            course.approved_students_count,
            round(sum(participations) / len(participations), 2) if participations else 0,
            round(sum(notes) / len(notes), 2) if notes else 0,
            max((latest.get(assignment.pk) or assignment.creado_en for assignment in course_assignments), default=None).replace(tzinfo=None),
        ])
    output = BytesIO()
    workbook.save(output)
    response = HttpResponse(output.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="estadisticas_cursos.xlsx"'
    return response
