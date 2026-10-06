from django.urls import path
from . import views
from evaluaciones.views import assignment_create
from quiz_generation.views import generate_form, generation_status, generation_status_json, import_json_view

urlpatterns = [
    path('', views.quiz_list, name='quiz_list'),
    path('create/', views.quiz_create, name='quiz_create'),
    path('generate/', generate_form, name='generate_quiz'),
    path('generate/import-json/', import_json_view, name='import_quiz_json'),
    path('generate/<int:job_id>/', generation_status, name='generation_status'),
    path('generate/<int:job_id>/status/', generation_status_json, name='generation_status_json'),

    path('<int:quiz_id>/edit/', views.quiz_edit, name='quiz_edit'),
    path('<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    path('<int:quiz_id>/builder/', views.quiz_builder, name='quiz_builder'),
    path('<int:quiz_id>/duplicate/', views.duplicate_quiz_view, name='duplicate_quiz'),
    path('<int:quiz_id>/publish/', views.toggle_publish, name='toggle_publish'),
    path('<int:quiz_id>/verify/', views.verify_quiz, name='verify_quiz'),
    path('<int:quiz_id>/verify/<int:attempt_id>/', views.verify_result, name='verify_result'),
    path('<int:quiz_id>/asignar/', assignment_create, name='assignment_create'),
    path('<int:quiz_id>/questions/add/', views.add_question, name='add_question'),
    path('<int:quiz_id>/questions/<int:question_id>/edit/', views.edit_question, name='edit_question'),
    path('<int:quiz_id>/questions/<int:question_id>/delete/', views.delete_question, name='delete_question'),
    path('<int:quiz_id>/questions/reorder/', views.reorder_questions_api, name='reorder_questions_api'),
]
