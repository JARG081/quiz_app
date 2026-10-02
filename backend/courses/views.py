from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone
from users.views import role_required
from .models import Course, CourseTeacher, Enrollment
from .forms import CourseForm
from .services import request_course_enrollment, pending_requests_for_teacher, resolve_enrollment_request


@role_required('ADMIN')
def course_list(request):
    courses = Course.objects.annotate(
        approved_students_count=Count('enrollments', filter=Q(enrollments__estado=Enrollment.APROBADA)),
        pending_requests_count=Count('enrollments', filter=Q(enrollments__estado=Enrollment.PENDIENTE)),
    ).prefetch_related('teachers').all()
    return render(request, 'courses/course_list.html', {'courses': courses})


@role_required('ADMIN')
def course_create(request):
    form = CourseForm()
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            course.creado_por = request.user
            course.save()
            messages.success(request, 'Curso creado.')
            return redirect('course_list')
    return render(request, 'courses/course_form.html', {'action': 'Crear', 'form': form})


@role_required('ADMIN')
def course_edit(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    form = CourseForm(instance=course)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, 'Curso actualizado.')
            return redirect('course_list')
    return render(request, 'courses/course_form.html', {'course': course, 'action': 'Editar', 'form': form})


@role_required('ADMIN')
def course_delete(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        course.delete()
        messages.success(request, 'Curso eliminado.')
        return redirect('course_list')
    return render(request, 'courses/confirm_delete.html', {'course': course})


@role_required('ADMIN')
def course_detail(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    docentes = User.objects.filter(profile__role='DOCENTE')
    estudiantes = User.objects.filter(profile__role='ESTUDIANTE')
    assigned_teachers = CourseTeacher.objects.filter(course=course).select_related('teacher')
    enrolled_students = Enrollment.objects.filter(course=course, estado=Enrollment.APROBADA).select_related('student', 'resuelto_por')
    pending_requests = Enrollment.objects.filter(course=course, estado=Enrollment.PENDIENTE).select_related('student')
    return render(request, 'courses/course_detail.html', {
        'course': course,
        'docentes': docentes,
        'estudiantes': estudiantes,
        'assigned_teachers': assigned_teachers,
        'enrolled_students': enrolled_students,
        'pending_requests': pending_requests,
    })


@role_required('ADMIN')
def assign_teacher(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        teacher_id = request.POST.get('teacher_id')
        teacher = get_object_or_404(User, pk=teacher_id)
        CourseTeacher.objects.get_or_create(course=course, teacher=teacher)
        messages.success(request, f'{teacher.username} asignado como docente.')
    return redirect('course_detail', course_id=course_id)


@role_required('ADMIN')
def remove_teacher(request, course_id, teacher_id):
    CourseTeacher.objects.filter(course_id=course_id, teacher_id=teacher_id).delete()
    messages.success(request, 'Docente removido.')
    return redirect('course_detail', course_id=course_id)


@role_required('ADMIN')
def enroll_student(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        student_id = request.POST.get('student_id')
        student = get_object_or_404(User, pk=student_id)
        enrollment, _ = Enrollment.objects.get_or_create(course=course, student=student)
        enrollment.estado = Enrollment.APROBADA
        enrollment.resuelto_por = request.user
        enrollment.resuelto_en = timezone.now()
        enrollment.save(update_fields=['estado', 'resuelto_por', 'resuelto_en'])
        messages.success(request, f'{student.username} inscrito en el curso.')
    return redirect('course_detail', course_id=course_id)


@role_required('ESTUDIANTE')
def request_enrollment(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        _, changed, message = request_course_enrollment(request.user, course)
        if changed:
            messages.success(request, message)
        else:
            messages.info(request, message)
    return redirect('estudiante_dashboard')


@role_required('DOCENTE')
def enrollment_requests(request):
    requests_qs = pending_requests_for_teacher(request.user)
    return render(request, 'courses/enrollment_requests.html', {'requests': requests_qs})


def _resolve_enrollment(request, enrollment_id, approve):
    enrollment = get_object_or_404(Enrollment.objects.select_related('course', 'student'), pk=enrollment_id)
    success, message = resolve_enrollment_request(enrollment, request.user, approve)
    if success:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect('enrollment_requests')


@role_required('DOCENTE')
def approve_enrollment_request(request, enrollment_id):
    if request.method != 'POST':
        return redirect('enrollment_requests')
    return _resolve_enrollment(request, enrollment_id, True)


@role_required('DOCENTE')
def reject_enrollment_request(request, enrollment_id):
    if request.method != 'POST':
        return redirect('enrollment_requests')
    return _resolve_enrollment(request, enrollment_id, False)


@role_required('ADMIN')
def unenroll_student(request, course_id, student_id):
    Enrollment.objects.filter(course_id=course_id, student_id=student_id).delete()
    messages.success(request, 'Estudiante removido.')
    return redirect('course_detail', course_id=course_id)
