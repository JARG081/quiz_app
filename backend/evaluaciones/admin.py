from django.contrib import admin

from .models import Asignacion, Intento, RespuestaIntento

admin.site.register(Asignacion)
admin.site.register(Intento)
admin.site.register(RespuestaIntento)
