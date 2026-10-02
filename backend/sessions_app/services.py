from django.db.models import Count, Sum, Q
from django.utils import timezone

from courses.models import CourseTeacher, Enrollment
from quizzes.models import Quiz
from .models import LiveAnswer, SessionParticipant


def option_stats_for_question(session, question):
    """Return option statistics for a question in a session."""
    answers = LiveAnswer.objects.filter(session=session, question=question)
    total_answers = answers.count()
    votes_by_option = {
        row['option_id']: row['votes']
        for row in answers.values('option_id').annotate(votes=Count('id'))
    }

    options = []
    for option in question.options.order_by('letra'):
        votes = votes_by_option.get(option.pk, 0)
        percentage = int(round(float(votes) / total_answers * 100, 0)) if total_answers > 0 else 0
        options.append({
            'letra': option.letra,
            'texto': option.texto,
            'es_correcta': option.es_correcta,
            'votos': votes,
            'porcentaje': percentage,
            'width_attr': f'style="width: {percentage}%"',
        })

    return options, total_answers


def session_leaderboard(session, limit=6):
    """Return the top scores for a session."""
    ranking = LiveAnswer.objects.filter(session=session).values(
        'student__username', 'student__pk'
    ).annotate(total_score=Sum('puntaje')).order_by('-total_score')[:limit]

    return [
        {
            'posicion': index + 1,
            'username': row['student__username'],
            'score': row['total_score'] or 0,
        }
        for index, row in enumerate(ranking)
    ]


def student_correct_answers(session, student):
    """Return how many answers a student got correct in a session."""
    return LiveAnswer.objects.filter(
        session=session,
        student=student,
        option__es_correcta=True,
    ).count()


def session_participant_results(session):
    """Return per-participant rows for the results screen and exports."""
    total_questions = session.total_preguntas()
    aggregate_by_student = {
        row['student_id']: row
        for row in LiveAnswer.objects.filter(session=session).values('student_id').annotate(
            score=Sum('puntaje'),
            correctas=Count('id', filter=Q(option__es_correcta=True)),
            respondidas=Count('id'),
        )
    }

    rows = []
    participants = SessionParticipant.objects.filter(session=session).select_related('student').order_by('student__username')
    for participant in participants:
        summary = aggregate_by_student.get(participant.student_id, {})
        correctas = summary.get('correctas') or 0
        respondidas = summary.get('respondidas') or 0
        rows.append({
            'student_id': participant.student_id,
            'username': participant.student.username,
            'score': summary.get('score') or 0,
            'correctas': correctas,
            'respondidas': respondidas,
            'total_preguntas': total_questions,
            'porcentaje': int(round((correctas / total_questions) * 100, 0)) if total_questions else 0,
            'expulsado': participant.expulsado,
        })
    return rows


def active_session_for_teacher(user):
    from .models import QuizSession

    return QuizSession.objects.filter(
        docente=user,
        estado__in=[QuizSession.ESPERA, QuizSession.EN_CURSO, QuizSession.PAUSADO],
    ).first()


def teacher_can_access_quiz(user, quiz):
    return CourseTeacher.objects.filter(teacher=user, course=quiz.course).exists()


def get_session_by_code(code):
    from .models import QuizSession

    return QuizSession.objects.filter(codigo=code).select_related('quiz', 'docente').first()


def session_can_accept_student(session, student):
    from .models import QuizSession

    if session.estado == QuizSession.FINALIZADO:
        return False, 'Esta sesión ya finalizó.'
    if not session.permitir_ingreso:
        return False, 'El ingreso está cerrado.'
    if not Enrollment.objects.filter(course=session.quiz.course, student=student, estado=Enrollment.APROBADA).exists():
        return False, 'No estás inscrito en el curso de este quiz.'
    return True, ''


def pause_session(session):
    if session.estado != session.EN_CURSO:
        return False
    session.estado = session.PAUSADO
    session.pausa_inicio = timezone.now()
    session.save(update_fields=['estado', 'pausa_inicio'])
    return True


def resume_session(session):
    if session.estado != session.PAUSADO or not session.pausa_inicio:
        return False
    paused_seconds = int((timezone.now() - session.pausa_inicio).total_seconds())
    session.tiempo_pausa_acumulado += paused_seconds
    session.pausa_inicio = None
    session.estado = session.EN_CURSO
    session.save(update_fields=['estado', 'pausa_inicio', 'tiempo_pausa_acumulado'])
    return True
