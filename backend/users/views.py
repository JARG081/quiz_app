from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from .models import Profile


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
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        role = request.POST.get('role', 'ESTUDIANTE')

        if not username or not password:
            messages.error(request, 'Usuario y contraseña son obligatorios.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Ese nombre de usuario ya existe.')
        elif role not in ['ADMIN', 'DOCENTE', 'ESTUDIANTE']:
            messages.error(request, 'Rol inválido.')
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.role = role
            profile.save()
            messages.success(request, f'Usuario {username} creado exitosamente.')
            return redirect('admin_dashboard')

    return render(request, 'users/create_user.html')


@role_required('ADMIN')
def edit_user(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    profile, _ = Profile.objects.get_or_create(user=target)

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        role = request.POST.get('role', profile.role)
        password = request.POST.get('password', '').strip()

        target.email = email
        if password:
            target.set_password(password)
        target.save()

        if role in ['ADMIN', 'DOCENTE', 'ESTUDIANTE']:
            profile.role = role
            profile.save()

        messages.success(request, 'Usuario actualizado.')
        return redirect('admin_dashboard')

    return render(request, 'users/edit_user.html', {'target': target, 'profile': profile})


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
    from courses.models import CourseTeacher
    mis_cursos = CourseTeacher.objects.filter(
        teacher=request.user
    ).select_related('course')
    return render(request, 'users/docente_dashboard.html', {'mis_cursos': mis_cursos})


# ─── Estudiante Dashboard ────────────────────────────────────────────────────

@role_required('ESTUDIANTE')
def estudiante_dashboard(request):
    from courses.models import Enrollment
    mis_cursos = Enrollment.objects.filter(
        student=request.user
    ).select_related('course')
    return render(request, 'users/estudiante_dashboard.html', {'mis_cursos': mis_cursos})
