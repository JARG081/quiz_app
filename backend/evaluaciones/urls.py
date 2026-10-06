from django.urls import path

from . import views

urlpatterns = [
    path('', views.assignment_list, name='assignment_list'),
    path('<int:assignment_id>/', views.assignment_results, name='assignment_results'),
    path('<int:assignment_id>/close/', views.assignment_close, name='assignment_close'),
    path('<int:assignment_id>/extend/', views.assignment_extend, name='assignment_extend'),
    path('<int:assignment_id>/delete/', views.assignment_delete, name='assignment_delete'),
    path('<int:assignment_id>/iniciar/', views.start_attempt, name='start_attempt'),
    path('intento/<int:intento_id>/', views.attempt_view, name='attempt_view'),
    path('intento/<int:intento_id>/responder/', views.answer_attempt, name='answer_attempt'),
    path('intento/<int:intento_id>/enviar/', views.submit_attempt, name='submit_attempt'),
    path('intento/<int:intento_id>/revision/', views.attempt_review, name='attempt_review'),
]
