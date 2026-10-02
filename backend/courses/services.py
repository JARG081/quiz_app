from django.utils import timezone

from .models import CourseTeacher, Enrollment


def request_course_enrollment(student, course):
    enrollment, created = Enrollment.objects.get_or_create(course=course, student=student)

    if enrollment.estado == Enrollment.APROBADA:
        return enrollment, False, 'Ya estás inscrito en este curso.'

    if enrollment.estado == Enrollment.PENDIENTE and not created:
        return enrollment, False, 'Tu solicitud ya está pendiente.'

    enrollment.estado = Enrollment.PENDIENTE
    enrollment.resuelto_en = None
    enrollment.resuelto_por = None
    enrollment.save(update_fields=['estado', 'resuelto_en', 'resuelto_por'])
    return enrollment, True, 'Solicitud enviada al docente.'


def pending_requests_for_teacher(teacher):
    return Enrollment.objects.filter(
        course__teachers__teacher=teacher,
        estado=Enrollment.PENDIENTE,
    ).select_related('course', 'student')


def resolve_enrollment_request(enrollment, teacher, approve):
    if not CourseTeacher.objects.filter(course=enrollment.course, teacher=teacher).exists():
        return False, 'No tienes permiso para gestionar este curso.'

    if enrollment.estado != Enrollment.PENDIENTE:
        return False, 'La solicitud ya fue resuelta.'

    enrollment.estado = Enrollment.APROBADA if approve else Enrollment.RECHAZADA
    enrollment.resuelto_por = teacher
    enrollment.resuelto_en = timezone.now()
    enrollment.save(update_fields=['estado', 'resuelto_por', 'resuelto_en'])
    return True, 'Solicitud aprobada.' if approve else 'Solicitud rechazada.'