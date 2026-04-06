import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from users.views import role_required
from courses.models import CourseTeacher, Enrollment
from quizzes.models import Quiz
from .models import QuizSession, SessionParticipant, LiveAnswer


# ─── Helper ──────────────────────────────────────────────────────────────────

def _auto_advance_if_needed(session):
    """Auto-advance question if timer expired. Returns True if advanced."""
    if session.estado != QuizSession.EN_CURSO:
        return False
    if not session.ultima_pregunta_inicio:
        return False

    tiempo_restante = session.tiempo_restante()
    if tiempo_restante > 0:
        return False

    # Timer expired → advance
    total = session.total_preguntas()
    if session.pregunta_actual >= total:
        # End session
        session.estado = QuizSession.FINALIZADO
        session.fecha_fin = timezone.now()
        session.save()
    else:
        session.pregunta_actual += 1
        session.ultima_pregunta_inicio = timezone.now()
        session.save()
    return True


# ─── Docente: Session Management ─────────────────────────────────────────────

@role_required('DOCENTE')
def create_session(request):
    # Rule: One active session per teacher
    active_session = QuizSession.objects.filter(
        docente=request.user, estado__in=[QuizSession.ESPERA, QuizSession.EN_CURSO]
    ).first()
    
    if active_session:
        messages.warning(request, 'Ya tienes una sesión activa. Termínala primero para empezar un nuevo Quiz.')
        if active_session.estado == QuizSession.EN_CURSO:
            return redirect('live_session_docente', session_id=active_session.pk)
        return redirect('waiting_room_docente', session_id=active_session.pk)

    if request.method == 'POST':
        from courses.models import CourseTeacher
        quiz_id = request.POST.get('quiz_id')
        quiz = get_object_or_404(Quiz, pk=quiz_id, publicado=True)
        
        mis_cursos = [ct.course for ct in CourseTeacher.objects.filter(teacher=request.user)]
        if quiz.course not in mis_cursos:
            messages.error(request, 'No tienes acceso a ese quiz.')
            return redirect('quiz_list')

        session = QuizSession.objects.create(quiz=quiz, docente=request.user)
        messages.success(request, f'Sesión creada con código: {session.codigo}')
        return redirect('waiting_room_docente', session_id=session.pk)
    
    return redirect('quiz_list')


@role_required('DOCENTE')
def session_list(request):
    sessions = QuizSession.objects.filter(docente=request.user).select_related('quiz').order_by('-id')
    return render(request, 'sessions_app/session_list.html', {'sessions': sessions})


@role_required('DOCENTE')
def waiting_room_docente(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    return render(request, 'sessions_app/waiting_room_docente.html', {'session': session})


@role_required('DOCENTE')
def live_session_docente(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    if session.estado == QuizSession.ESPERA:
        return redirect('waiting_room_docente', session_id=session_id)
    return render(request, 'sessions_app/live_session_docente.html', {'session': session})


# ─── Estudiante: Join/Play ────────────────────────────────────────────────────

@role_required('ESTUDIANTE')
def join_session(request):
    if request.method == 'POST':
        codigo = request.POST.get('codigo', '').strip().upper()
        try:
            session = QuizSession.objects.get(codigo=codigo)
        except QuizSession.DoesNotExist:
            messages.error(request, 'Código de sesión no encontrado.')
            return redirect('estudiante_dashboard')

        if session.estado == QuizSession.FINALIZADO:
            messages.error(request, 'Esta sesión ya finalizó.')
            return redirect('estudiante_dashboard')

        if not session.permitir_ingreso:
            messages.error(request, 'El ingreso está cerrado.')
            return redirect('estudiante_dashboard')

        # Check enrollment
        enrolled = Enrollment.objects.filter(
            course=session.quiz.course, student=request.user
        ).exists()
        if not enrolled:
            messages.error(request, 'No estás inscrito en el curso de este quiz.')
            return redirect('estudiante_dashboard')

        participant, created = SessionParticipant.objects.get_or_create(
            session=session, student=request.user,
            defaults={'activo': True, 'expulsado': False}
        )
        if participant.expulsado:
            messages.error(request, 'Fuiste expulsado de esta sesión.')
            return redirect('estudiante_dashboard')

        participant.activo = True
        participant.save()

        if session.estado == QuizSession.EN_CURSO:
            return redirect('live_session_estudiante', session_id=session.pk)
        return redirect('waiting_room_estudiante', session_id=session.pk)

    return render(request, 'sessions_app/join_session.html')


@role_required('ESTUDIANTE')
def waiting_room_estudiante(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id)
    participant = get_object_or_404(SessionParticipant, session=session, student=request.user)
    if participant.expulsado:
        messages.error(request, 'Fuiste expulsado de esta sesión.')
        return redirect('estudiante_dashboard')
    return render(request, 'sessions_app/waiting_room_estudiante.html', {
        'session': session, 'participant': participant
    })


@role_required('ESTUDIANTE')
def live_session_estudiante(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id)
    try:
        participant = SessionParticipant.objects.get(session=session, student=request.user)
    except SessionParticipant.DoesNotExist:
        return redirect('join_session')

    if participant.expulsado:
        messages.error(request, 'Fuiste expulsado de esta sesión.')
        return redirect('estudiante_dashboard')

    return render(request, 'sessions_app/live_session_estudiante.html', {
        'session': session,
        'participant': participant
    })


# ─── AJAX Polling API ─────────────────────────────────────────────────────────

def session_state_api(request, session_id):
    """Polling endpoint — returns full session state."""
    session = get_object_or_404(QuizSession, pk=session_id)

    # Auto-advance if timer expired
    _auto_advance_if_needed(session)
    session.refresh_from_db()

    pregunta_obj = session.pregunta_actual_obj()
    participants = session.participantes_activos()
    participant_count = participants.count()

    # Count answers for current question
    answers_count = 0
    if pregunta_obj:
        answers_count = LiveAnswer.objects.filter(
            session=session, question=pregunta_obj
        ).count()

    # For enrolled student: did they answer?
    student_answered = False
    student_expulsado = False
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        if request.user.profile.role == 'ESTUDIANTE':
            try:
                p = SessionParticipant.objects.get(session=session, student=request.user)
                student_expulsado = p.expulsado
                if pregunta_obj:
                    student_answered = LiveAnswer.objects.filter(
                        session=session, student=request.user, question=pregunta_obj
                    ).exists()
            except SessionParticipant.DoesNotExist:
                pass

    data = {
        'estado': session.estado,
        'pregunta_actual': session.pregunta_actual,
        'total_preguntas': session.total_preguntas(),
        'tiempo_restante': session.tiempo_restante(),
        'participant_count': participant_count,
        'answers_count': answers_count,
        'permitir_ingreso': session.permitir_ingreso,
        'student_answered': student_answered,
        'student_expulsado': student_expulsado,
        'mostrando_resultados': session.mostrando_resultados,
    }

    if session.mostrando_resultados and student_answered and pregunta_obj:
        user_ans = LiveAnswer.objects.filter(session=session, student=request.user, question=pregunta_obj).select_related('option').first()
        if user_ans:
            correct_opts = [o.letra for o in pregunta_obj.options.filter(es_correcta=True)]
            data['student_result'] = {
                'es_correcta': user_ans.option.es_correcta,
                'puntaje': user_ans.puntaje,
                'letra_marcada': user_ans.option.letra,
                'correct_opts': correct_opts
            }

    if pregunta_obj:
        data['pregunta'] = {
            'id': pregunta_obj.pk,
            'enunciado': pregunta_obj.enunciado,
            'orden': pregunta_obj.orden,
            'opciones': [
                {'id': o.pk, 'letra': o.letra, 'texto': o.texto}
                for o in pregunta_obj.options.order_by('letra')
            ]
        }
    else:
        data['pregunta'] = None

    return JsonResponse(data)


def participants_api(request, session_id):
    """Returns list of active participants."""
    session = get_object_or_404(QuizSession, pk=session_id)
    participants = session.participantes_activos().select_related('student')

    pregunta_obj = session.pregunta_actual_obj()
    answered_ids = set()
    if pregunta_obj:
        answered_ids = set(LiveAnswer.objects.filter(
            session=session, question=pregunta_obj
        ).values_list('student_id', flat=True))

    data = {
        'participants': [
            {
                'id': p.student.pk,
                'username': p.student.username,
                'answered': p.student.pk in answered_ids,
            }
            for p in participants
        ]
    }
    return JsonResponse(data)


def results_api(request, session_id, question_orden):
    """Returns vote counts per option for a given question (by orden)."""
    session = get_object_or_404(QuizSession, pk=session_id)
    questions = list(session.quiz.questions.prefetch_related('options').order_by('orden'))

    idx = int(question_orden) - 1
    if idx < 0 or idx >= len(questions):
        return JsonResponse({'error': 'Pregunta no encontrada'}, status=404)

    question = questions[idx]
    options = question.options.order_by('letra')

    total_answers = LiveAnswer.objects.filter(session=session, question=question).count()
    result = []
    for opt in options:
        count = LiveAnswer.objects.filter(session=session, question=question, option=opt).count()
        porcentaje = int(round(float(count) / total_answers * 100, 0)) if total_answers > 0 else 0
        result.append({
            'letra': opt.letra,
            'texto': opt.texto,
            'es_correcta': opt.es_correcta,
            'votos': count,
            'porcentaje': porcentaje,
            'width_attr': f'style="width: {porcentaje}%;"',
        })

    return JsonResponse({'opciones': result, 'total': total_answers})


# ─── Docente Actions ──────────────────────────────────────────────────────────

@require_POST
@role_required('DOCENTE')
def start_session(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    if session.estado != QuizSession.ESPERA:
        return JsonResponse({'error': 'La sesión ya fue iniciada.'}, status=400)

    session.estado = QuizSession.EN_CURSO
    session.fecha_inicio = timezone.now()
    session.pregunta_actual = 1
    session.ultima_pregunta_inicio = timezone.now()
    session.save()
    return JsonResponse({'ok': True, 'session_id': session.pk})


@require_POST
@role_required('DOCENTE')
def next_question(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    if session.estado != QuizSession.EN_CURSO:
        return JsonResponse({'error': 'La sesión no está en curso.'}, status=400)

    force = request.POST.get('force', 'false').lower() == 'true'
    pregunta_obj = session.pregunta_actual_obj()

    if pregunta_obj:
        participants = session.participantes_activos()
        total_active = participants.count()
        answered = LiveAnswer.objects.filter(session=session, question=pregunta_obj).count()
        pending = total_active - answered

        if pending > 0 and not force:
            return JsonResponse({'needs_confirm': True, 'pending': pending})

    total = session.total_preguntas()
    if session.pregunta_actual >= total:
        session.estado = QuizSession.FINALIZADO
        session.fecha_fin = timezone.now()
        session.save()
        return JsonResponse({'ok': True, 'finalizado': True})
    else:
        session.pregunta_actual += 1
        session.ultima_pregunta_inicio = timezone.now()
        session.save()
        return JsonResponse({'ok': True, 'finalizado': False, 'pregunta_actual': session.pregunta_actual})


@require_POST
@role_required('DOCENTE')
def close_admission(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    session.permitir_ingreso = False
    session.save()
    return JsonResponse({'ok': True})


@require_POST
@role_required('DOCENTE')
def expel_student(request, session_id, student_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    participant = get_object_or_404(SessionParticipant, session=session, student_id=student_id)
    participant.expulsado = True
    participant.activo = False
    participant.save()
    return JsonResponse({'ok': True})


@require_POST
@role_required('DOCENTE')
def end_session(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id, docente=request.user)
    session.estado = QuizSession.FINALIZADO
    session.fecha_fin = timezone.now()
    session.permitir_ingreso = False
    session.save()
    return JsonResponse({'ok': True})


# ─── Estudiante Actions ───────────────────────────────────────────────────────

@require_POST
@role_required('ESTUDIANTE')
def submit_answer(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id)

    if session.estado != QuizSession.EN_CURSO:
        return JsonResponse({'error': 'Sesión no activa.'}, status=400)

    try:
        participant = SessionParticipant.objects.get(session=session, student=request.user)
    except SessionParticipant.DoesNotExist:
        return JsonResponse({'error': 'No participas en esta sesión.'}, status=403)

    if participant.expulsado:
        return JsonResponse({'error': 'Fuiste expulsado.'}, status=403)

    # Check timer
    if session.tiempo_restante() == 0:
        return JsonResponse({'error': 'El tiempo ha expirado.'}, status=400)

    pregunta_obj = session.pregunta_actual_obj()
    if not pregunta_obj:
        return JsonResponse({'error': 'No hay pregunta activa.'}, status=400)

    # Check not already answered
    if LiveAnswer.objects.filter(session=session, student=request.user, question=pregunta_obj).exists():
        return JsonResponse({'error': 'Ya respondiste esta pregunta.'}, status=400)

    option_id = request.POST.get('option_id')
    from quizzes.models import Option
    option = get_object_or_404(Option, pk=option_id, question=pregunta_obj)

    puntaje = 0
    if option.es_correcta:
        elapsed = (timezone.now() - session.ultima_pregunta_inicio).total_seconds()
        tiempo_total = session.quiz.tiempo_por_pregunta
        respuestas_previas = LiveAnswer.objects.filter(
            session=session, question=pregunta_obj, option__es_correcta=True
        ).count()
        
        if respuestas_previas == 0:
            puntaje = 1000
        else:
            penalizacion_tiempo = int((elapsed / tiempo_total) * 500) if tiempo_total > 0 else 0
            penalizacion_posicion = 50 * respuestas_previas
            puntaje = max(100, 1000 - penalizacion_posicion - penalizacion_tiempo)

    LiveAnswer.objects.create(
        session=session, student=request.user,
        question=pregunta_obj, option=option, puntaje=puntaje
    )
    return JsonResponse({'ok': True})


def leaderboard_api(request, session_id):
    """Devuelve el leaderboard parcial de toda la sesión (top 6 puntajes altos)."""
    from django.db.models import Sum
    session = get_object_or_404(QuizSession, pk=session_id)
    
    ranking = LiveAnswer.objects.filter(session=session).values(
        'student__username', 'student__pk'
    ).annotate(total_score=Sum('puntaje')).order_by('-total_score')[:6]
    
    data = []
    for i, r in enumerate(ranking):
        data.append({
            'posicion': i + 1,
            'username': r['student__username'],
            'score': r['total_score'] or 0
        })
        
    return JsonResponse({'ranking': data})


# ─── Session Results ──────────────────────────────────────────────────────────

def session_results(request, session_id):
    session = get_object_or_404(QuizSession, pk=session_id)
    questions = list(session.quiz.questions.prefetch_related('options').order_by('orden'))

    results = []
    for q in questions:
        opts = []
        total_votos_q = LiveAnswer.objects.filter(session=session, question=q).count()
        for opt in q.options.order_by('letra'):
            count = LiveAnswer.objects.filter(session=session, question=q, option=opt).count()
            porcentaje = int(round(float(count) / total_votos_q * 100, 0)) if total_votos_q > 0 else 0
            opts.append({'letra': opt.letra, 'texto': opt.texto, 'es_correcta': opt.es_correcta, 'votos': count, 'porcentaje': porcentaje, 'width_attr': f'style="width: {porcentaje}%;"'})
        results.append({'pregunta': q, 'opciones': opts})

    # Student score
    student_score = None
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        if request.user.profile.role == 'ESTUDIANTE':
            correct = LiveAnswer.objects.filter(
                session=session, student=request.user, option__es_correcta=True
            ).count()
            student_score = {'correctas': correct, 'total': len(questions)}

    from django.db.models import Sum
    ranking_data = LiveAnswer.objects.filter(session=session).values(
        'student__username'
    ).annotate(total_score=Sum('puntaje')).order_by('-total_score')[:5]
    
    leaderboard = []
    for i, r in enumerate(ranking_data):
        leaderboard.append({
            'posicion': i + 1,
            'username': r['student__username'],
            'score': r['total_score'] or 0
        })

    return render(request, 'sessions_app/session_results.html', {
        'session': session,
        'results': results,
        'student_score': student_score,
        'leaderboard': leaderboard,
    })
