from django.db import models
from django.contrib.auth.models import User
from sales.models import Lead

class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('LEAD_ASSIGNED', 'Lead Assigned'),
        ('LEAD_REMOVED', 'Lead Removed'),
        ('DEAL_REQUEST_NEW', 'New Deal Request'),
        ('DEAL_APPROVED', 'Deal Approved'),
        ('DEAL_REJECTED', 'Deal Rejected'),
        ('AGENT_CONFIG_UPDATE', 'Agent Config Updated'),
        ('NEW_COMMENT', 'New Comment on Lead'),
        ('SYSTEM_ALERT', 'System Alert'),
        ('SCRAPER_STATUS', 'Scraper Status'),
    )
    
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', help_text="The user receiving the notification")
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications', help_text="The user who triggered this (can be null for system)")
    
    type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    
    # Optional target URL for clicking the notification
    target_url = models.CharField(max_length=500, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        
    def __str__(self):
        return f"[{self.get_type_display()}] to {self.recipient.username}: {self.title}"
