from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.models import User
from users.views import role_required
from .models import Course, CourseTeacher, Enrollment


@role_required('ADMIN')
def course_list(request):
    courses = Course.objects.prefetch_related('teachers', 'enrollments').all()
    return render(request, 'courses/course_list.html', {'courses': courses})


@role_required('ADMIN')
def course_create(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        if not nombre:
            messages.error(request, 'El nombre es obligatorio.')
        else:
            Course.objects.create(nombre=nombre, descripcion=descripcion, creado_por=request.user)
            messages.success(request, 'Curso creado.')
            return redirect('course_list')
    return render(request, 'courses/course_form.html', {'action': 'Crear'})


@role_required('ADMIN')
def course_edit(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        course.nombre = request.POST.get('nombre', course.nombre).strip()
        course.descripcion = request.POST.get('descripcion', course.descripcion).strip()
        course.save()
        messages.success(request, 'Curso actualizado.')
        return redirect('course_list')
    return render(request, 'courses/course_form.html', {'course': course, 'action': 'Editar'})


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
    from users.models import Profile
    # All docentes and estudiantes for selects
    docentes = User.objects.filter(profile__role='DOCENTE')
    estudiantes = User.objects.filter(profile__role='ESTUDIANTE')
    assigned_teachers = CourseTeacher.objects.filter(course=course).select_related('teacher')
    enrolled_students = Enrollment.objects.filter(course=course).select_related('student')
    return render(request, 'courses/course_detail.html', {
        'course': course,
        'docentes': docentes,
        'estudiantes': estudiantes,
        'assigned_teachers': assigned_teachers,
        'enrolled_students': enrolled_students,
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
        Enrollment.objects.get_or_create(course=course, student=student)
        messages.success(request, f'{student.username} inscrito en el curso.')
    return redirect('course_detail', course_id=course_id)


@role_required('ADMIN')
def unenroll_student(request, course_id, student_id):
    Enrollment.objects.filter(course_id=course_id, student_id=student_id).delete()
    messages.success(request, 'Estudiante removido.')
    return redirect('course_detail', course_id=course_id)
