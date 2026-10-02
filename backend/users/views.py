from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.core.mail import send_mail
from django.template.loader import render_to_string
from .models import Profile
from .forms import AdminUserCreateForm, AdminUserEditForm, ForgotPasswordForm, ResetPasswordForm


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
    mis_cursos = Enrollment.objects.filter(
        student=request.user
    ).select_related('course').order_by('course__nombre')
    approved_courses = mis_cursos.filter(estado=Enrollment.APROBADA)
    pending_requests = mis_cursos.filter(estado=Enrollment.PENDIENTE)
    rejected_requests = mis_cursos.filter(estado=Enrollment.RECHAZADA)
    available_courses = Course.objects.filter(
        teachers__isnull=False,
    ).exclude(enrollments__student=request.user).distinct().order_by('nombre')
    return render(request, 'users/estudiante_dashboard.html', {
        'mis_cursos': approved_courses,
        'pending_requests': pending_requests,
        'rejected_requests': rejected_requests,
        'available_courses': available_courses,
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
            user = User.objects.get(email=email)
            
            # Generar token seguro
            token_generator = PasswordResetTokenGenerator()
            token = token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Construir URL de reset
            reset_url = request.build_absolute_uri(
                f'/reset-password/{uid}/{token}/'
            )
            
            # Enviar email
            try:
                subject = 'Recuperación de contraseña - Quiz Platform'
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
                send_mail(subject, message, 'noreply@quizplatform.local', [email])
                messages.success(request, 'Se envió un enlace de recuperación a tu correo.')
                return redirect('login')
            except Exception as e:
                messages.error(request, 'Error al enviar el correo. Intenta más tarde.')

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
