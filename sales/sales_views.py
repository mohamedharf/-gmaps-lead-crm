from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from sales.models import Lead, OutreachStatus, SalesAgentProfile, SubscriptionOrder, AgentHistoryLog
from sales.forms import SalesAgentProfileForm
import json


@login_required
def my_profile(request):
    """Sales agent can view their own profile (self-service)"""
    # Get current user (the logged-in sales agent)
    agent = request.user
    
    # Ensure user is in Sales group
    if not agent.groups.filter(name='Sales').exists():
        return HttpResponse("Access denied - Sales agents only", status=403)
    
    # Get or create sales profile
    sales_profile, created = SalesAgentProfile.objects.get_or_create(user=agent)
    
    # Get assigned leads (Combine M2M and Legacy fallback directly to avoid empty M2M unmasking all leads)
    assigned_leads = Lead.objects.filter(
        Q(assigned_agents=agent) | Q(assigned_to=agent)
    ).distinct()
    
    # Calculate statistics
    total_leads = assigned_leads.count()
    
    # Status breakdown
    status_breakdown = assigned_leads.values('outreach_status__status').annotate(
        count=Count('id')
    )
    
    # Convert to dict for easy access
    status_dict = {
        'NOT_CONTACTED': 0,
        'SENT': 0,
        'DELIVERED': 0,
        'READ': 0,
        'REPLIED': 0,
        'INTERESTED': 0,
        'DEAL': 0,
        'NOT_INTERESTED': 0
    }
    
    for item in status_breakdown:
        status = item['outreach_status__status']
        if status in status_dict:
            status_dict[status] = item['count']
    
    # Calculate conversion rate
    deals_count = status_dict.get('DEAL', 0)
    conversion_rate = (deals_count / total_leads * 100) if total_leads > 0 else 0
    
    # Get recent activity (last 30 days performance)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_deals = assigned_leads.filter(
        outreach_status__status='DEAL',
        outreach_status__last_contact_date__gte=thirty_days_ago
    ).order_by('-outreach_status__last_contact_date')[:5]
    
    # Get subordinates for manager dashboard
    subordinates = []
    if sales_profile.subordinates.exists():
        subordinates = sales_profile.subordinates.select_related('user').annotate(
            assigned_count=Count('user__assigned_leads')
        ).order_by('user__username')
    
    context = {
        'agent': agent,
        'sales_profile': sales_profile,
        'total_leads': total_leads,
        'status_dict': status_dict,
        'deals_count': deals_count,
        'conversion_rate': round(conversion_rate, 2),
        'assigned_leads': assigned_leads.select_related('outreach_status', 'contact_details'),
        'recent_deals': recent_deals,
        'subordinates': subordinates,
        'history_logs': AgentHistoryLog.objects.filter(agent=agent).order_by('-created_at')[:10],
        'is_self_view': True,  # Flag to indicate this is self-service view
    }
    
    return render(request, 'sales/my_profile.html', context)


@login_required
def my_commissions(request):
    """Sales agent can view their own commissions and earnings"""
    # Ensure user is in Sales group
    if not request.user.groups.filter(name='Sales').exists() and not request.user.is_staff:
        return HttpResponse("Access denied", status=403)
    
    # Get completed direct orders for this agent
    orders = SubscriptionOrder.objects.filter(
        sales_agent=request.user,
        status='COMPLETED'
    ).order_by('-paid_at')
    
    # Calculate direct stats
    total_commission = sum(order.commission_amount for order in orders)
    total_revenue = sum(order.price for order in orders)
    
    # Get team commissions for managers
    team_orders = SubscriptionOrder.objects.filter(
        manager=request.user,
        status='COMPLETED'
    ).order_by('-paid_at')
    
    total_team_commission = sum(order.manager_commission_amount for order in team_orders)
    combined_earnings = total_commission + total_team_commission
    
    context = {
        'orders': orders,
        'total_commission': total_commission,
        'total_revenue': total_revenue,
        'orders_count': orders.count(),
        'team_orders': team_orders,
        'total_team_commission': total_team_commission,
        'combined_earnings': combined_earnings,
        'is_manager': team_orders.exists() or (hasattr(request.user, 'sales_profile') and request.user.sales_profile.subordinates.exists())
    }
    
    return render(request, 'sales/my_commissions.html', context)


@login_required
def sales_agent_profile(request, agent_id):
    """Display comprehensive profile page for a sales agent"""
    agent = get_object_or_404(User, id=agent_id)
    
    # Check authorization: must be staff OR the agent's manager
    is_authorized = request.user.is_staff
    
    if not is_authorized and hasattr(agent, 'sales_profile') and agent.sales_profile.manager:
        if agent.sales_profile.manager.user == request.user:
            is_authorized = True
            
    if not is_authorized:
        return HttpResponse("Unauthorized - Admin or Manager access required", status=403)
    
    # Get or create sales profile
    sales_profile, created = SalesAgentProfile.objects.get_or_create(user=agent)
    
    # Get assigned leads (Combine M2M and Legacy fallback directly to avoid empty M2M unmasking all leads)
    assigned_leads = Lead.objects.filter(
        Q(assigned_agents=agent) | Q(assigned_to=agent)
    ).distinct()
    
    # Calculate statistics
    total_leads = assigned_leads.count()
    
    # Status breakdown
    status_breakdown = assigned_leads.values('outreach_status__status').annotate(
        count=Count('id')
    )
    
    # Convert to dict for easy access
    status_dict = {
        'NOT_CONTACTED': 0,
        'SENT': 0,
        'DELIVERED': 0,
        'READ': 0,
        'REPLIED': 0,
        'INTERESTED': 0,
        'DEAL': 0,
        'NOT_INTERESTED': 0
    }
    
    for item in status_breakdown:
        status = item['outreach_status__status']
        if status in status_dict:
            status_dict[status] = item['count']
    
    # Calculate conversion rate
    deals_count = status_dict.get('DEAL', 0)
    conversion_rate = (deals_count / total_leads * 100) if total_leads > 0 else 0
    
    # Get recent activity (last 30 days performance)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    recent_deals = assigned_leads.filter(
        outreach_status__status='DEAL',
        outreach_status__last_contact_date__gte=thirty_days_ago
    ).order_by('-outreach_status__last_contact_date')[:5]
    
    # Get all other sales agents for transfer dropdown
    # Staff sees everyone; Team Lead sees only their own subordinates (excluding the viewed agent)
    if request.user.is_staff:
        other_agents = User.objects.filter(
            groups__name='Sales'
        ).exclude(id=agent_id).order_by('username')
    else:
        # Team Lead: only their subordinates excluding the viewed agent (themselves can be added in template)
        subordinate_user_ids = SalesAgentProfile.objects.filter(
            manager__user=request.user
        ).values_list('user_id', flat=True)
        other_agents = User.objects.filter(
            id__in=subordinate_user_ids
        ).exclude(id=agent_id).order_by('username')
    
    # Get available managers (Sales agents excluding self)
    managers = User.objects.filter(groups__name='Sales').exclude(id=agent_id)
    
    # Get subordinates for manager dashboard
    subordinates = []
    if sales_profile.subordinates.exists():
        subordinates = sales_profile.subordinates.select_related('user').annotate(
            assigned_count=Count('user__assigned_leads')
        ).order_by('user__username')
    
    # Get history logs for this agent
    from .models import AgentHistoryLog
    history_logs = AgentHistoryLog.objects.filter(agent=agent).order_by('-created_at')
    
    context = {
        'agent': agent,
        'sales_profile': sales_profile,
        'total_leads': total_leads,
        'status_dict': status_dict,
        'deals_count': deals_count,
        'conversion_rate': round(conversion_rate, 2),
        'assigned_leads': assigned_leads.select_related('outreach_status', 'contact_details').prefetch_related('assigned_agents'),
        'recent_deals': recent_deals.select_related('outreach_status'),
        'other_agents': other_agents,
        'managers': managers,
        'subordinates': subordinates,
        'history_logs': history_logs,
    }
    
    return render(request, 'sales/sales_agent_profile.html', context)


@login_required
def update_agent_config(request, agent_id):
    """Admin can update sales agent configuration (like commission rate and names)"""
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    agent_user = get_object_or_404(User, id=agent_id)
    profile, created = SalesAgentProfile.objects.get_or_create(user=agent_user)
    
    if request.method == 'POST':
        # Update User fields (First Name, Last Name)
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        user_changes = []
        
        if first_name is not None and agent_user.first_name != first_name:
            agent_user.first_name = first_name
            user_changes.append(f"First Name: {first_name}")
        if last_name is not None and agent_user.last_name != last_name:
            agent_user.last_name = last_name
            user_changes.append(f"Last Name: {last_name}")
            
        if user_changes:
            agent_user.save()

        form = SalesAgentProfileForm(request.POST, instance=profile)
        if form.is_valid():
            # Check what's changing for the log
            changes = user_changes.copy()
            if 'commission_rate' in form.changed_data:
                changes.append(f"Commission Rate: {form.cleaned_data['commission_rate']}%")
            if 'team_commission_rate' in form.changed_data:
                changes.append(f"Team Rate: {form.cleaned_data['team_commission_rate']}%")
            if 'manager_user' in form.changed_data:
                mgr = form.cleaned_data.get('manager_user')
                changes.append(f"Manager: {mgr.username if mgr else 'None'}")
                
            form.save()
            
            if changes:
                from .models import AgentHistoryLog
                AgentHistoryLog.objects.create(
                    agent=agent_user,
                    action_by=request.user,
                    action_type='CONFIG_UPDATE',
                    details="Updated configuration: " + ", ".join(changes)
                )
                
                # Fire Notification
                if agent_user != request.user:
                    from notifications.utils import create_notification
                    create_notification(
                        recipient=agent_user,
                        sender=request.user,
                        notification_type='AGENT_CONFIG_UPDATE',
                        title="Profile Configuration Updated",
                        message=f"Admin {request.user.username} updated your profile: " + ", ".join(changes),
                        target_url=f"/agent/{agent_id}/"
                    )
            
            return redirect('sales_agent_profile', agent_id=agent_id)
    
    return redirect('sales_agent_profile', agent_id=agent_id)


@login_required
def transfer_leads(request, agent_id):
    """Transfer specific leads from one agent to another (Staff or Manager authorized)"""
    agent_user = get_object_or_404(User, id=agent_id)
    
    # Check authorization: staff OR the agent's manager
    is_authorized = request.user.is_staff
    if not is_authorized and hasattr(agent_user, 'sales_profile') and agent_user.sales_profile.manager:
        if agent_user.sales_profile.manager.user == request.user:
            is_authorized = True
            
    if not is_authorized:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lead_ids = data.get('lead_ids', [])
            target_agent_id = data.get('target_agent_id')
            
            if not lead_ids or not target_agent_id:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Missing lead_ids or target_agent_id'
                }, status=400)
            
            target_agent = get_object_or_404(User, id=target_agent_id)
            
            # Additional authorization for target agent if not staff
            if not request.user.is_staff:
                is_target_valid = (target_agent == request.user) or \
                                 (hasattr(target_agent, 'sales_profile') and \
                                  target_agent.sales_profile.manager and \
                                  target_agent.sales_profile.manager.user == request.user)
                if not is_target_valid:
                    return JsonResponse({'status': 'error', 'message': 'Cannot transfer to an agent outside your team'}, status=403)
            
            # Transfer leads
            leads = Lead.objects.filter(id__in=lead_ids)
            for lead in leads:
                # Remove current agent from M2M
                lead.assigned_agents.remove(agent_user)
                # Add target agent
                lead.assigned_agents.add(target_agent)
                # Sync legacy field for compatibility
                lead.assigned_to = target_agent
                lead.save()
            
            updated_count = leads.count()
            
            # Log the transfer
            from .models import AgentHistoryLog
            AgentHistoryLog.objects.create(
                agent=agent_user,
                action_by=request.user,
                action_type='LEAD_TRANSFER',
                details=f"Transferred {updated_count} leads to {target_agent.username}"
            )
            
            # Fire Notifications
            from notifications.utils import create_notification
            
            if updated_count > 0:
                if agent_user != request.user:
                    create_notification(
                        recipient=agent_user,
                        sender=request.user,
                        notification_type='LEAD_REMOVED',
                        title="Leads Transferred",
                        message=f"{updated_count} leads were transferred from your portfolio to {target_agent.username} by {request.user.username}."
                    )
                
                if target_agent != request.user:
                    create_notification(
                        recipient=target_agent,
                        sender=request.user,
                        notification_type='LEAD_ASSIGNED',
                        title="New Leads Assigned",
                        message=f"{updated_count} leads were transferred to your portfolio from {agent_user.username} by {request.user.username}.",
                        target_url='/my-profile/'
                    )
            
            return JsonResponse({
                'status': 'success',
                'message': f'{updated_count} leads transferred to {target_agent.username}',
                'count': updated_count
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@login_required
def remove_leads(request, agent_id):
    """Remove assignment from specific leads (Staff or Manager authorized)"""
    agent_user = get_object_or_404(User, id=agent_id)
    
    # Check authorization: staff OR the agent's manager
    is_authorized = request.user.is_staff
    if not is_authorized and hasattr(agent_user, 'sales_profile') and agent_user.sales_profile.manager:
        if agent_user.sales_profile.manager.user == request.user:
            is_authorized = True
            
    if not is_authorized:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            lead_ids = data.get('lead_ids', [])
            
            if not lead_ids:
                return JsonResponse({
                    'status': 'error',
                    'message': 'No lead_ids provided'
                }, status=400)
            
            # Remove assignment
            leads = Lead.objects.filter(id__in=lead_ids)
            for lead in leads:
                lead.assigned_agents.remove(agent_user)
                if lead.assigned_to == agent_user:
                    # Update legacy field - find another if exists or set None
                    other_agent = lead.assigned_agents.first()
                    lead.assigned_to = other_agent
                lead.save()
            
            updated_count = leads.count()
            
            # Log entry
            from .models import AgentHistoryLog
            AgentHistoryLog.objects.create(
                agent=agent_user,
                action_by=request.user,
                action_type='LEAD_TRANSFER', # Assuming action_type is LEAD_TRANSFER since action_details is used
                details=f"Unassigned {updated_count} leads"
            )
            
            # Fire Notification
            if updated_count > 0 and agent_user != request.user:
                from notifications.utils import create_notification
                create_notification(
                    recipient=agent_user,
                    sender=request.user,
                    notification_type='LEAD_REMOVED',
                    title="Leads Removed",
                    message=f"{updated_count} leads were removed from your portfolio by {request.user.username}."
                )
            
            return JsonResponse({
                'status': 'success',
                'message': f'{updated_count} leads unassigned',
                'count': updated_count
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@login_required
def bulk_transfer_leads(request, agent_id):
    """Transfer ALL leads from one agent to another (Staff or Manager authorized)"""
    agent_user = get_object_or_404(User, id=agent_id)
    
    # Check authorization: staff OR the agent's manager
    is_authorized = request.user.is_staff
    if not is_authorized and hasattr(agent_user, 'sales_profile') and agent_user.sales_profile.manager:
        if agent_user.sales_profile.manager.user == request.user:
            is_authorized = True
            
    if not is_authorized:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            target_agent_id = data.get('target_agent_id')
            
            if not target_agent_id:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Missing target_agent_id'
                }, status=400)
            
            target_agent = get_object_or_404(User, id=target_agent_id)
            
            # Additional authorization for target agent if not staff
            if not request.user.is_staff:
                is_target_valid = (target_agent == request.user) or \
                                 (hasattr(target_agent, 'sales_profile') and \
                                  target_agent.sales_profile.manager and \
                                  target_agent.sales_profile.manager.user == request.user)
                if not is_target_valid:
                    return JsonResponse({'status': 'error', 'message': 'Cannot transfer to an agent outside your team'}, status=403)
                    
            agent_user = get_object_or_404(User, id=agent_id)
            
            # Transfer ALL leads
            leads = Lead.objects.filter(
                Q(assigned_agents=agent_user) | Q(assigned_to=agent_user)
            ).distinct()
            
            for lead in leads:
                lead.assigned_agents.remove(agent_user)
                lead.assigned_agents.add(target_agent)
                lead.assigned_to = target_agent
                lead.save()
            
            updated_count = leads.count()
            
            # Fire Notifications
            if updated_count > 0:
                from notifications.utils import create_notification
                
                if agent_user != request.user:
                    create_notification(
                        recipient=agent_user,
                        sender=request.user,
                        notification_type='LEAD_REMOVED',
                        title="All Leads Transferred",
                        message=f"All your {updated_count} leads were transferred to {target_agent.username} by {request.user.username}."
                    )
                
                if target_agent != request.user:
                    create_notification(
                        recipient=target_agent,
                        sender=request.user,
                        notification_type='LEAD_ASSIGNED',
                        title="Mass Leads Assigned",
                        message=f"{updated_count} leads were transferred to your portfolio from {agent_user.username} by {request.user.username}.",
                        target_url='/my-profile/'
                    )
            
            return JsonResponse({
                'status': 'success',
                'message': f'All {updated_count} leads transferred to {target_agent.username}',
                'count': updated_count
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)


@login_required
def agent_performance_stats(request, agent_id):
    """API endpoint to get agent performance statistics for charts"""
    agent = get_object_or_404(User, id=agent_id)
    
    # Allow if user is staff OR if user is viewing their own stats
    if not request.user.is_staff and request.user.id != agent_id:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    # Get date range (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # Daily stats for the last 30 days
    daily_stats = []
    for i in range(30):
        date = timezone.now().date() - timedelta(days=i)
        
        # Count deals closed on this day
        deals_count = Lead.objects.filter(
            Q(assigned_agents=agent) | Q(assigned_to=agent),
            outreach_status__status='DEAL',
            outreach_status__last_contact_date__date=date
        ).distinct().count()
        
        # Count messages sent on this day
        messages_sent = Lead.objects.filter(
            Q(assigned_agents=agent) | Q(assigned_to=agent),
            outreach_status__last_contact_date__date=date
        ).exclude(outreach_status__status='NOT_CONTACTED').distinct().count()
        
        daily_stats.append({
            'date': date.strftime('%Y-%m-%d'),
            'deals': deals_count,
            'messages': messages_sent
        })
    
    # Reverse to show oldest to newest
    daily_stats.reverse()
    
    return JsonResponse({
        'status': 'success',
        'data': {
            'daily_stats': daily_stats
        }
    })


@login_required
def agent_history_full(request, agent_id):
    """Full-page view of all history logs for a specific agent"""
    agent = get_object_or_404(User, id=agent_id)
    
    # Check authorization: must be staff OR the agent's manager
    is_authorized = request.user.is_staff
    
    if not is_authorized and hasattr(agent, 'sales_profile') and agent.sales_profile.manager:
        if agent.sales_profile.manager.user == request.user:
            is_authorized = True
            
    if not is_authorized and request.user.id == agent.id:
        # Agents can also view their own history
        is_authorized = True

    if not is_authorized:
        return HttpResponse("Unauthorized", status=403)
    
    # Get all logs for this agent
    from .models import AgentHistoryLog
    history_logs = AgentHistoryLog.objects.filter(agent=agent).order_by('-created_at')
    
    return render(request, 'sales/agent_history_full.html', {
        'agent': agent,
        'history_logs': history_logs
    })
