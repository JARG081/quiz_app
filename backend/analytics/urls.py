from django.urls import path
from . import views

urlpatterns = [
    path('student/', views.student_stats, name='student_stats'),
    path('docente/', views.docente_stats, name='docente_stats'),
]
