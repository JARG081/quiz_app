from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Profile(models.Model):
    ADMIN = 'ADMIN'
    DOCENTE = 'DOCENTE'
    ESTUDIANTE = 'ESTUDIANTE'
    ROLE_CHOICES = [
        (ADMIN, 'Admin'),
        (DOCENTE, 'Docente'),
        (ESTUDIANTE, 'Estudiante'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default=ESTUDIANTE)
    alias = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f'{self.display_name()} ({self.role})'

    def display_name(self):
        if self.alias and self.alias.strip():
            return self.alias.strip()
        full_name = self.user.get_full_name().strip()
        if full_name:
            return full_name
        return self.user.username

    def is_admin(self):
        return self.role == self.ADMIN

    def is_docente(self):
        return self.role == self.DOCENTE

    def is_estudiante(self):
        return self.role == self.ESTUDIANTE

    def dashboard_url(self):
        if self.role == self.ADMIN:
            return '/admin/dashboard/'
        elif self.role == self.DOCENTE:
            return '/docente/dashboard/'
        else:
            return '/estudiante/dashboard/'


@receiver(post_save, sender=User)
def create_or_update_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
