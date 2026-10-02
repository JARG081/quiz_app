from django.shortcuts import render, get_object_or_404
from users.views import role_required
from sessions_app.models import QuizSession, LiveAnswer, SessionParticipant
from sessions_app.services import option_stats_for_question, student_correct_answers


@role_required('ESTUDIANTE')
def student_stats(request):
    # All sessions where student participated and session is finished
    participations = SessionParticipant.objects.filter(
        student=request.user,
        session__estado='FINALIZADO'
    ).select_related('session__quiz__course')

    quiz_stats = []
    total_correct = 0
    total_questions = 0

    for p in participations:
        session = p.session
        quiz = session.quiz
        q_total = quiz.questions.count()
        correct = student_correct_answers(session, request.user)
        score = int(round(float(correct) / q_total * 100, 0)) if q_total > 0 else 0
        quiz_stats.append({
            'quiz': quiz,
            'session': session,
            'correctas': correct,
            'total': q_total,
            'score': score,
            'width_attr': f'style="width: {score}%;"',
        })
        total_correct += correct
        total_questions += q_total

    avg_general = int(round(float(total_correct) / total_questions * 100, 0)) if total_questions > 0 else 0

    return render(request, 'analytics/student_stats.html', {
        'quiz_stats': quiz_stats,
        'avg_general': avg_general,
    })


@role_required('DOCENTE')
def docente_stats(request):
    from courses.models import CourseTeacher
    mis_cursos = [ct.course for ct in CourseTeacher.objects.filter(teacher=request.user)]
    sessions = QuizSession.objects.filter(
        docente=request.user, estado='FINALIZADO'
    ).select_related('quiz__course').prefetch_related('quiz__questions')

    quiz_stats = []
    for session in sessions:
        quiz = session.quiz
        participants = SessionParticipant.objects.filter(session=session, expulsado=False)
        q_total = quiz.questions.count()

        student_scores = []
        for p in participants:
            correct = LiveAnswer.objects.filter(
                session=session, student=p.student, option__es_correcta=True
            ).count()
            score = int(round(float(correct) / q_total * 100, 0)) if q_total > 0 else 0
            student_scores.append(score)

        avg = int(round(sum(student_scores) / len(student_scores), 0)) if student_scores else 0

        # Answer distribution per question
        question_data = []
        for q in quiz.questions.prefetch_related('options').order_by('orden'):
            opts, _total_votos_q = option_stats_for_question(session, q)
            question_data.append({'enunciado': q.enunciado[:60], 'opciones': opts})

        quiz_stats.append({
            'session': session,
            'quiz': quiz,
            'participantes': len(student_scores),
            'avg_score': avg,
            'pregunta_data': question_data,
        })

    return render(request, 'analytics/docente_stats.html', {
        'quiz_stats': quiz_stats,
        'mis_cursos': mis_cursos,
    })
