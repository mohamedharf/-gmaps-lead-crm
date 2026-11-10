from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Notification

@login_required
def get_unread_count(request):
    """API endpoint to get the count of unread notifications and the latest 5"""
    notifications = Notification.objects.filter(recipient=request.user)
    unread_count = notifications.filter(is_read=False).count()
    
    latest_notifications = notifications.order_by('-created_at')[:5]
    
    data = []
    for notif in latest_notifications:
        data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'type_display': notif.get_type_display(),
            'is_read': notif.is_read,
            'time_ago': notif.created_at.strftime("%Y-%m-%d %H:%M"),
            'url': notif.target_url or "#"
        })
        
    return JsonResponse({
        'unread_count': unread_count,
        'notifications': data
    })

@login_required
def mark_all_as_read(request):
    """API endpoint to mark all notifications for the user as read"""
    if request.method == "POST":
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return JsonResponse({"status": "success"})
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=400)

@login_required
def mark_as_read(request, notification_id):
    """API endpoint to mark a single notification as read"""
    if request.method == "POST":
        try:
            notif = Notification.objects.get(id=notification_id, recipient=request.user)
            notif.is_read = True
            notif.save()
            return JsonResponse({"status": "success"})
        except Notification.DoesNotExist:
            return JsonResponse({"status": "error", "message": "Notification not found"}, status=404)
    return JsonResponse({"status": "error", "message": "Invalid method"}, status=400)

@login_required
def notifications_list(request):
    """Render the full page of all notifications for a user"""
    notifications = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    
    return render(request, 'sales/list.html', {
        'notifications': notifications
    })
