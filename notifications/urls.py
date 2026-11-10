from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # API endpoints for AJAX
    path('api/unread-count/', views.get_unread_count, name='unread_count'),
    path('api/mark-all-read/', views.mark_all_as_read, name='mark_all_read'),
    path('api/mark-read/<int:notification_id>/', views.mark_as_read, name='mark_read'),
    
    # Full list page
    path('', views.notifications_list, name='list'),
]
