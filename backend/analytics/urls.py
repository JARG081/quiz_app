from django.urls import path
from . import views

urlpatterns = [
    path('student/', views.student_stats, name='student_stats'),
    path('docente/', views.docente_stats, name='docente_stats'),
    path('admin/', views.admin_stats, name='admin_stats'),
    path('admin/course/<int:course_id>/', views.admin_course_detail, name='admin_course_detail'),
    path('admin/export/', views.admin_course_export, name='admin_course_export'),
]
