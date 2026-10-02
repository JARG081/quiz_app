from django.urls import path
from . import views

urlpatterns = [
    path('', views.course_list, name='course_list'),
    path('create/', views.course_create, name='course_create'),
    path('<int:course_id>/', views.course_detail, name='course_detail'),
    path('<int:course_id>/edit/', views.course_edit, name='course_edit'),
    path('<int:course_id>/delete/', views.course_delete, name='course_delete'),
    path('<int:course_id>/teachers/assign/', views.assign_teacher, name='assign_teacher'),
    path('<int:course_id>/teachers/<int:teacher_id>/remove/', views.remove_teacher, name='remove_teacher'),
    path('<int:course_id>/students/enroll/', views.enroll_student, name='enroll_student'),
    path('<int:course_id>/students/request/', views.request_enrollment, name='request_enrollment'),
    path('<int:course_id>/students/<int:student_id>/unenroll/', views.unenroll_student, name='unenroll_student'),
    path('requests/', views.enrollment_requests, name='enrollment_requests'),
    path('requests/<int:enrollment_id>/approve/', views.approve_enrollment_request, name='approve_enrollment_request'),
    path('requests/<int:enrollment_id>/reject/', views.reject_enrollment_request, name='reject_enrollment_request'),
]
