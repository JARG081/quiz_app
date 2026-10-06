from django.urls import path

from . import views

urlpatterns = [
    path('', views.generate_form, name='generate_quiz'),
    path('import-json/', views.import_json_view, name='import_quiz_json'),
    path('<int:job_id>/', views.generation_status, name='generation_status'),
    path('<int:job_id>/status/', views.generation_status_json, name='generation_status_json'),
]

