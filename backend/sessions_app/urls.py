from django.urls import path
from . import views

urlpatterns = [
    path('', views.session_list, name='session_list'),
    path('create/', views.create_session, name='create_session'),
    path('join/', views.join_session, name='join_session'),

    # Docente
    path('<int:session_id>/waiting/', views.waiting_room_docente, name='waiting_room_docente'),
    path('<int:session_id>/live/', views.live_session_docente, name='live_session_docente'),
    path('<int:session_id>/start/', views.start_session, name='start_session'),
    path('<int:session_id>/next/', views.next_question, name='next_question'),
    path('<int:session_id>/pause/', views.pause_session_view, name='pause_session'),
    path('<int:session_id>/resume/', views.resume_session_view, name='resume_session'),
    path('<int:session_id>/close-admission/', views.close_admission, name='close_admission'),
    path('<int:session_id>/end/', views.end_session, name='end_session'),
    path('<int:session_id>/expel/<int:student_id>/', views.expel_student, name='expel_student'),

    # Estudiante
    path('<int:session_id>/play/', views.waiting_room_estudiante, name='waiting_room_estudiante'),
    path('<int:session_id>/quiz/', views.live_session_estudiante, name='live_session_estudiante'),
    path('<int:session_id>/answer/', views.submit_answer, name='submit_answer'),

    # Shared
    path('<int:session_id>/results/', views.session_results, name='session_results'),
    path('<int:session_id>/results/pdf/', views.export_results_pdf, name='export_results_pdf'),
    path('<int:session_id>/results/xlsx/', views.export_results_xlsx, name='export_results_xlsx'),

    # Polling API
    path('<int:session_id>/api/state/', views.session_state_api, name='session_state_api'),
    path('<int:session_id>/api/participants/', views.participants_api, name='participants_api'),
    path('<int:session_id>/api/results/<int:question_orden>/', views.results_api, name='results_api'),
    path('<int:session_id>/api/leaderboard/', views.leaderboard_api, name='leaderboard_api'),
]
