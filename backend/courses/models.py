from django.db import models
from django.contrib.auth.models import User


class Course(models.Model):
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    creado_por = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='courses_created'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre

    class Meta:
        ordering = ['-fecha_creacion']


class CourseTeacher(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='teachers')
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name='teaching_courses')
    fecha_asignacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('course', 'teacher')

    def __str__(self):
        return f'{self.teacher.username} → {self.course.nombre}'


class Enrollment(models.Model):
    PENDIENTE = 'PENDIENTE'
    APROBADA = 'APROBADA'
    RECHAZADA = 'RECHAZADA'
    ESTADO_CHOICES = [
        (PENDIENTE, 'Pendiente'),
        (APROBADA, 'Aprobada'),
        (RECHAZADA, 'Rechazada'),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrolled_courses')
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default=PENDIENTE)
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)
    resuelto_en = models.DateTimeField(null=True, blank=True)
    resuelto_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollment_resolutions',
    )

    class Meta:
        unique_together = ('course', 'student')

    def __str__(self):
        return f'{self.student.username} → {self.course.nombre} ({self.estado})'
