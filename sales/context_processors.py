from .models import SystemSettings, Dataset

def global_settings(request):
    """
    Inject global system settings (branding, product name, etc) and datasets into all templates.
    """
    context = {}
    
    # System Settings
    try:
        settings = SystemSettings.get_settings()
        context['sys_settings'] = settings
    except Exception:
        pass
        
    # Datasets for Sidebar
    if request.user.is_authenticated:
        try:
            if request.user.is_staff:
                context['all_datasets'] = Dataset.objects.all().order_by('-created_at')
            else:
                from django.db.models import Q
                # Show datasets where the user or their subordinates are assigned leads
                context['all_datasets'] = Dataset.objects.filter(
                    Q(leads__assigned_to=request.user) | 
                    Q(leads__assigned_agents=request.user) |
                    Q(leads__assigned_to__sales_profile__manager__user=request.user) |
                    Q(leads__assigned_agents__sales_profile__manager__user=request.user)
                ).distinct().order_by('-created_at')
        except Exception:
            pass

        # Pending deal requests count for admin badge
        try:
            from .models import DealRequest
            context['pending_deals_count'] = DealRequest.objects.filter(status='PENDING').count()
        except Exception:
            context['pending_deals_count'] = 0

    return context
