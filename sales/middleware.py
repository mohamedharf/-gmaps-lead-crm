from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone


class ActivityTrackingMiddleware(MiddlewareMixin):
    """
    Middleware to automatically track user activity
    Updates last_active_at field for sales agents every request
    """
    
    def process_request(self, request):
        if request.user.is_authenticated:
            # Check if user has sales_profile
            if hasattr(request.user, 'sales_profile'):
                from sales.models import SalesAgentProfile
                
                # Update last activity time
                SalesAgentProfile.objects.filter(user=request.user).update(
                    last_active_at=timezone.now(),
                    is_active_session=True
                )
        
        return None
