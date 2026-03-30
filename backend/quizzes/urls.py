from django.urls import path
from . import views

urlpatterns = [
    path('', views.quiz_list, name='quiz_list'),
    path('create/', views.quiz_create, name='quiz_create'),
    path('<int:quiz_id>/edit/', views.quiz_edit, name='quiz_edit'),
    path('<int:quiz_id>/delete/', views.quiz_delete, name='quiz_delete'),
    path('<int:quiz_id>/builder/', views.quiz_builder, name='quiz_builder'),
    path('<int:quiz_id>/publish/', views.toggle_publish, name='toggle_publish'),
    path('<int:quiz_id>/questions/add/', views.add_question, name='add_question'),
    path('<int:quiz_id>/questions/<int:question_id>/edit/', views.edit_question, name='edit_question'),
    path('<int:quiz_id>/questions/<int:question_id>/delete/', views.delete_question, name='delete_question'),
]
