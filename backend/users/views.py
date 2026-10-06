from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction

from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.template.loader import render_to_string
from .models import Profile
from .forms import AdminUserCreateForm, AdminUserEditForm, ForgotPasswordForm, OwnProfileForm, ResetPasswordForm


# ─── Mixins / Decorators ────────────────────────────────────────────────────

def role_required(*roles):
    """Redirect to own dashboard if role doesn't match (no 403)."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            try:
                profile = request.user.profile
            except Profile.DoesNotExist:
                return redirect('/login/')
            if profile.role in roles:
                return view_func(request, *args, **kwargs)
            return redirect(profile.dashboard_url())
        return _wrapped
    return decorator


# ─── Auth ────────────────────────────────────────────────────────────────────

def login_view(request):
    if request.user.is_authenticated:
        try:
            return redirect(request.user.profile.dashboard_url())
        except Profile.DoesNotExist:
            pass

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            try:
                return redirect(user.profile.dashboard_url())
            except Profile.DoesNotExist:
                return redirect('/')
        else:
            messages.error(request, 'Usuario o contraseña incorrectos.')
    return render(request, 'users/login.html')


def logout_view(request):
    logout(request)
    return redirect('/login/')


def google_login_view(request):
    """Google/Gmail Login for Docentes with Alias & Offline Access."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        alias = request.POST.get('alias', '').strip()
        local_password = request.POST.get('local_password', '').strip()

        if not email or not email.endswith('@gmail.com'):
            if '@' not in email:
                email = f'{email}@gmail.com'
        
        username = email.split('@')[0]
        existing = User.objects.filter(username=username).exclude(email=email).first()
        if existing:
            username = f"{username}_{User.objects.count() + 1}"

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'username': username,
                'first_name': 'Docente',
                'last_name': 'Gmail',
                'is_active': True,
            }
        )
        if created:
            if local_password:
                user.set_password(local_password)
            else:
                user.set_unusable_password()
            user.save()
        elif local_password:
            user.set_password(local_password)
            user.save()

        profile, _ = Profile.objects.get_or_create(user=user)
        if profile.role != 'DOCENTE':
            profile.role = 'DOCENTE'
        
        if alias:
            profile.alias = alias
        profile.save()

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session['gmail_oauth_connected'] = True
        messages.success(request, f'Sesión iniciada con Google/Gmail ({email}). Alias visible: {profile.display_name()}.')
        return redirect(profile.dashboard_url())

    return render(request, 'users/google_login.html')



@login_required
def profile_view(request):
    form = OwnProfileForm(request.POST or None, user=request.user, initial={
        'alias': getattr(request.user.profile, 'alias', '') or '',
        'email': request.user.email,
        'first_name': request.user.first_name,
        'last_name': request.user.last_name,
    })
    if request.method == 'POST' and form.is_valid():
        request.user.email = form.cleaned_data['email']
        request.user.first_name = form.cleaned_data['first_name']
        request.user.last_name = form.cleaned_data['last_name']
        if form.cleaned_data['new_password']:
            request.user.set_password(form.cleaned_data['new_password'])
        request.user.save()
        
        profile = request.user.profile
        profile.alias = form.cleaned_data['alias'].strip()
        profile.save()

        if form.cleaned_data['new_password']:
            login(request, request.user)
        messages.success(request, 'Perfil actualizado correctamente.')
        return redirect('profile')
    return render(request, 'users/profile.html', {'form': form})


# ─── Admin ────────────────────────────────────────────────────────────────────

@role_required('ADMIN')
def admin_dashboard(request):
    users = User.objects.select_related('profile').exclude(is_superuser=True).order_by('username')
    grupos = [
        {'titulo': 'Admins del Sistema', 'lista': [u for u in users if u.profile.role == 'ADMIN'], 'icon': '🛡️'},
        {'titulo': 'Docentes', 'lista': [u for u in users if u.profile.role == 'DOCENTE'], 'icon': '🎓'},
        {'titulo': 'Estudiantes', 'lista': [u for u in users if u.profile.role == 'ESTUDIANTE'], 'icon': '🧑‍💻'},
    ]
    return render(request, 'users/admin_dashboard.html', {'grupos': grupos, 'total': len(users)})


@role_required('ADMIN')
def create_user(request):
    form = AdminUserCreateForm()
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
            )
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = form.cleaned_data['role']
            profile.save()
            messages.success(request, f'Usuario {user.username} creado exitosamente.')
            return redirect('admin_dashboard')

    return render(request, 'users/create_user.html', {'form': form})


@role_required('ADMIN')
def edit_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    profile, _ = Profile.objects.get_or_create(user=target)
    form = AdminUserEditForm(initial={
        'email': target.email,
        'role': profile.role,
    })

    if request.method == 'POST':
        form = AdminUserEditForm(request.POST)
        if form.is_valid():
            target.email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            if password:
                target.set_password(password)
            target.save()

            profile.role = form.cleaned_data['role']
            profile.save()

            messages.success(request, 'Usuario actualizado.')
            return redirect('admin_dashboard')

    return render(request, 'users/edit_user.html', {'target': target, 'profile': profile, 'form': form})


@role_required('ADMIN')
def delete_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        target.delete()
        messages.success(request, 'Usuario eliminado.')
        return redirect('admin_dashboard')
    return render(request, 'users/confirm_delete_user.html', {'target': target})


@role_required('ADMIN')
def bulk_import_users_view(request):
    import csv
    import io
    import json
    from quiz_platform.audit import log_action

    if request.method == 'POST':
        raw_text = request.POST.get('raw_text', '').strip()
        file_obj = request.FILES.get('file_obj')
        default_role = request.POST.get('default_role', Profile.ESTUDIANTE)
        default_password = request.POST.get('default_password', 'Password123!')

        content = ''
        if file_obj:
            try:
                content = file_obj.read().decode('utf-8')
            except Exception:
                messages.error(request, 'El archivo no tiene una codificación UTF-8 válida.')
                return render(request, 'users/bulk_import_users.html')
        else:
            content = raw_text

        if not content:
            messages.error(request, 'Ingresa texto o sube un archivo CSV/JSON.')
            return render(request, 'users/bulk_import_users.html')

        created_count = 0
        updated_count = 0
        rows = []

        if content.strip().startswith('[') or content.strip().startswith('{'):
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    rows = data.get('usuarios', []) or data.get('users', [])
                elif isinstance(data, list):
                    rows = data
            except json.JSONDecodeError:
                rows = []

        if not rows:
            reader = csv.reader(io.StringIO(content))
            for line in reader:
                if not line or len(line) == 0:
                    continue
                if 'email' in line[0].lower() or 'correo' in line[0].lower():
                    continue
                email = line[0].strip()
                first_name = line[1].strip() if len(line) > 1 else ''
                last_name = line[2].strip() if len(line) > 2 else ''
                role_val = line[3].strip().upper() if len(line) > 3 else default_role
                rows.append({
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'role': role_val,
                })

        with transaction.atomic():
            for item in rows:
                if isinstance(item, dict):
                    email = item.get('email') or item.get('correo') or ''
                    first_name = item.get('first_name') or item.get('nombre') or ''
                    last_name = item.get('last_name') or item.get('apellido') or ''
                    role_val = str(item.get('role') or item.get('rol') or default_role).upper()
                else:
                    continue

                email = str(email).strip().lower()
                if not email or '@' not in email:
                    continue

                base_username = email.split('@')[0]
                username = base_username
                counter = 1
                while User.objects.filter(username=username).exclude(email=email).exists():
                    username = f"{base_username}{counter}"
                    counter += 1

                role = Profile.DOCENTE if 'DOCENTE' in role_val or 'PROFESOR' in role_val else Profile.ESTUDIANTE
                if 'ADMIN' in role_val:
                    role = Profile.ADMIN

                user = User.objects.filter(email=email).first()
                if not user:
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=default_password,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    created_count += 1
                else:
                    if first_name:
                        user.first_name = first_name
                    if last_name:
                        user.last_name = last_name
                    user.save()
                    updated_count += 1

                profile, _ = Profile.objects.get_or_create(user=user)
                profile.role = role
                profile.save()

        messages.success(request, f'Carga masiva completada: {created_count} usuarios creados, {updated_count} actualizados.')
        log_action('BULK_USER_IMPORT', request.user, {'creados': created_count, 'actualizados': updated_count})
        return redirect('admin_dashboard')

    return render(request, 'users/bulk_import_users.html')



# ─── Docente Dashboard ───────────────────────────────────────────────────────

@role_required('DOCENTE')
def docente_dashboard(request):
    from courses.models import CourseTeacher, Enrollment
    mis_cursos = CourseTeacher.objects.filter(
        teacher=request.user
    ).select_related('course')
    pending_requests_count = Enrollment.objects.filter(
        course__teachers__teacher=request.user,
        estado=Enrollment.PENDIENTE,
    ).count()
    return render(request, 'users/docente_dashboard.html', {
        'mis_cursos': mis_cursos,
        'pending_requests_count': pending_requests_count,
    })


# ─── Estudiante Dashboard ────────────────────────────────────────────────────

@role_required('ESTUDIANTE')
def estudiante_dashboard(request):
    from courses.models import Course, Enrollment
    from evaluaciones.models import Asignacion, Intento
    from evaluaciones.services import cerrar_intentos_vencidos, nota_final

    cerrar_intentos_vencidos()
    mis_cursos = Enrollment.objects.filter(
        student=request.user
    ).select_related('course').order_by('course__nombre')
    approved_courses = mis_cursos.filter(estado=Enrollment.APROBADA)
    pending_requests = mis_cursos.filter(estado=Enrollment.PENDIENTE)
    rejected_requests = mis_cursos.filter(estado=Enrollment.RECHAZADA)
    available_courses = Course.objects.filter(
        teachers__isnull=False,
    ).exclude(enrollments__student=request.user).distinct().order_by('nombre')

    assignments = Asignacion.objects.filter(
        quiz__course__enrollments__student=request.user,
        quiz__course__enrollments__estado=Enrollment.APROBADA,
    ).select_related('quiz', 'quiz__course').distinct().order_by('-cierra_en')
    quices_pendientes = []
    intentos_en_progreso = []
    quices_completados = []
    for assignment in assignments:
        progress = assignment.intentos.filter(
            estudiante=request.user,
            estado=Intento.EN_PROGRESO,
        ).first()
        best = nota_final(assignment, request.user)
        used = assignment.intentos.filter(estudiante=request.user).count()
        if progress:
            intentos_en_progreso.append(progress)
        elif best:
            best.assignment = assignment
            quices_completados.append(best)
        elif assignment.esta_abierta() and used < assignment.intentos_permitidos:
            assignment.intentos_usados = used
            quices_pendientes.append(assignment)

    return render(request, 'users/estudiante_dashboard.html', {
        'mis_cursos': approved_courses,
        'pending_requests': pending_requests,
        'rejected_requests': rejected_requests,
        'available_courses': available_courses,
        'quices_pendientes': quices_pendientes,
        'intentos_en_progreso': intentos_en_progreso,
        'quices_completados': quices_completados,
    })


# ─── Password Recovery ───────────────────────────────────────────────────────

def forgot_password(request):
    """Solicitar token de recuperación por correo."""
    if request.user.is_authenticated:
        try:
            return redirect(request.user.profile.dashboard_url())
        except Profile.DoesNotExist:
            pass

    form = ForgotPasswordForm()
    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            users = User.objects.filter(email__iexact=email)
            token_generator = PasswordResetTokenGenerator()

            for user in users:
                token = token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                reset_url = request.build_absolute_uri(
                    f'/reset-password/{uid}/{token}/'
                )
                message = f"""
Hola {user.username},

Recibimos una solicitud para recuperar tu contraseña.
Haz clic en el siguiente enlace para establecer una nueva contraseña:

{reset_url}

Este enlace es válido por 24 horas.

Si no solicitaste esto, ignora este correo.

Saludos,
Quiz Platform
                """
                try:
                    send_mail(
                        'Recuperación de contraseña - Quiz Platform',
                        message,
                        'noreply@quizplatform.local',
                        [user.email],
                    )
                except Exception:
                    pass

            messages.success(request, 'Si el correo existe, recibirás un enlace.')
            return redirect('login')

    return render(request, 'users/forgot_password.html', {'form': form})


def reset_password(request, uid, token):
    """Restablecer contraseña usando token."""
    if request.user.is_authenticated:
        try:
            return redirect(request.user.profile.dashboard_url())
        except Profile.DoesNotExist:
            pass

    try:
        # Decodificar UID
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        messages.error(request, 'Enlace de recuperación inválido o expirado.')
        return redirect('forgot_password')

    # Validar token
    token_generator = PasswordResetTokenGenerator()
    if not token_generator.check_token(user, token):
        messages.error(request, 'Enlace de recuperación inválido o expirado.')
        return redirect('forgot_password')

    form = ResetPasswordForm()
    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password'])
            user.save()
            messages.success(request, 'Contraseña restablecida. Inicia sesión con tu nueva contraseña.')
            return redirect('login')

    return render(request, 'users/reset_password.html', {'form': form, 'user': user})
