from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('google-login/', views.google_login_view, name='google_login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('reset-password/<str:uid>/<str:token>/', views.reset_password, name='reset_password'),
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/users/create/', views.create_user, name='create_user'),
    path('admin/users/bulk-import/', views.bulk_import_users_view, name='bulk_import_users'),
    path('admin/users/<int:user_id>/edit/', views.edit_user, name='edit_user'),

    path('admin/users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('docente/dashboard/', views.docente_dashboard, name='docente_dashboard'),
    path('estudiante/dashboard/', views.estudiante_dashboard, name='estudiante_dashboard'),
]
