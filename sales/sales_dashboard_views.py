from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from .models import SubscriptionOrder

@staff_member_required
def successful_sales_dashboard(request):
    """
    Dashboard for tracking successful sales, revenue, and commissions.
    Only accessible by staff members.
    """
    
    # Get Filter Parameters
    agent_filter = request.GET.get('agent')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Base Query: Only completed orders
    orders = SubscriptionOrder.objects.filter(status='COMPLETED').select_related('sales_agent', 'lead')
    
    # Apply Filters
    if agent_filter:
        orders = orders.filter(sales_agent_id=agent_filter)
        
    if date_from:
        orders = orders.filter(paid_at__date__gte=date_from)
        
    if date_to:
        orders = orders.filter(paid_at__date__lte=date_to)
    
    # Calculate Aggregates
    total_sales_count = orders.count()
    
    # Sum of price (Total Revenue)
    total_revenue = orders.aggregate(Sum('price'))['price__sum'] or 0
    
    # Calculate Total Commissions (agent + manager commissions)
    total_commissions = sum(
        order.commission_amount + order.manager_commission_amount for order in orders
    )

    # Calculate Net Revenue matching SubscriptionOrder.net_revenue
    net_revenue = total_revenue - total_commissions
    
    # Pagination (30 per page)
    from django.core.paginator import Paginator
    paginator = Paginator(orders, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get List of Sales Agents (for filter dropdown)
    # Only show agents who have at least one completed sale or are in Sales group
    sales_agents = User.objects.filter(
        Q(groups__name='Sales') | Q(sales_orders__status='COMPLETED')
    ).distinct()
    
    context = {
        'orders': page_obj,
        'total_sales': total_sales_count,
        'total_revenue': total_revenue,
        'total_commissions': total_commissions,
        'net_revenue': net_revenue,
        'sales_agents': sales_agents,
        # Pass filters back to template to keep state
        'selected_agent': int(agent_filter) if agent_filter else None, 
        'selected_date_from': date_from,
        'selected_date_to': date_to,
    }
    
    return render(request, 'sales/successful_sales_dashboard.html', context)
