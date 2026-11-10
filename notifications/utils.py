from .models import Notification

def create_notification(recipient, notification_type, title, message, sender=None, target_url=None):
    """
    Utility function to safely create a notification for a user.
    """
    if not recipient:
        return None
        
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        type=notification_type,
        title=title,
        message=message,
        target_url=target_url
    )
    return notification
