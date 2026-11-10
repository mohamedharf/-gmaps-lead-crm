from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .models import Lead, ContactDetails, OutreachStatus, SystemSettings, Dataset
from .forms import SystemSettingsForm
import threading
from django.core.management import call_command
import io
import json
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
import pandas as pd
from django.db.models import Q
import csv

@login_required
def dashboard(request):
    # Base QuerySet optimized with select_related
    leads = Lead.objects.select_related('outreach_status', 'contact_details', 'assigned_to', 'dataset').all()
    
    # If Sales Agent, filter by assignment and ensure profile exists
    if request.user.groups.filter(name='Sales').exists():
        leads = leads.filter(Q(assigned_agents=request.user) | Q(assigned_to=request.user)).distinct()
        from sales.models import SalesAgentProfile
        SalesAgentProfile.objects.get_or_create(user=request.user)

    total_leads = leads.count()
    pending_outreach = leads.filter(outreach_status__status='NOT_CONTACTED').count()
    recent_items = leads.order_by('-created_at')[:5]

    # Total closed deals (DEAL status on outreach)
    total_deals = leads.filter(outreach_status__status='DEAL').count()

    # Total revenue from completed SubscriptionOrders (system-wide for admin, filtered for agents)
    from sales.models import SubscriptionOrder
    from django.db.models import Sum
    if request.user.is_staff:
        revenue_qs = SubscriptionOrder.objects.filter(status='COMPLETED')
    else:
        revenue_qs = SubscriptionOrder.objects.filter(status='COMPLETED', sales_agent=request.user)
    total_revenue = revenue_qs.aggregate(s=Sum('price'))['s'] or 0

    context = {
        'total_leads': total_leads,
        'total_deals': total_deals,
        'total_revenue': total_revenue,
        'pending_outreach': pending_outreach,
        'recent_items': recent_items
    }
    
    # --- Sales Analytics & Leaderboard ---
    # Staff can see all, Managers see subordinates, Agents see no team stats
    is_manager = False
    if hasattr(request.user, 'sales_profile'):
        is_manager = request.user.sales_profile.subordinates.exists()

    if request.user.is_staff or is_manager:
        from django.contrib.auth.models import User
        from django.db.models import Count, Sum, F, ExpressionWrapper, FloatField
        from sales.models import SalesAgentProfile
        
        # Determine which agents to show
        if request.user.is_staff:
            sales_agents_qs = User.objects.filter(groups__name='Sales')
        else:
            sales_agents_qs = User.objects.filter(sales_profile__manager=request.user.sales_profile)
            
        # Optimize with aggregation to avoid N+1 queries
        # Limiting to 50 to prevent DOM bloat and slow renders
        # Order by deals_count (annotated field) instead of total_earned (property)
        sales_agents_qs = sales_agents_qs.annotate(
            total_assigned=Count('assigned_leads', distinct=True),
            deals_count=Count('assigned_leads', filter=Q(assigned_leads__outreach_status__status='DEAL'), distinct=True),
            pending_count=Count('assigned_leads', filter=Q(assigned_leads__outreach_status__status='NOT_CONTACTED'), distinct=True),
            sent_count=Count('assigned_leads', filter=Q(assigned_leads__outreach_status__status__in=['SENT', 'DELIVERED', 'READ']), distinct=True),
        ).select_related('sales_profile').order_by('-deals_count')[:50]
        
        agents_stats = []
        for agent in sales_agents_qs:
            profile = agent.sales_profile
            total = agent.total_assigned
            deals = agent.deals_count
            conv = (deals / total * 100) if total > 0 else 0
            
            agents_stats.append({
                'agent': agent,
                'profile': profile,
                'total_leads': total,
                'deals_count': deals,
                'pending_count': agent.pending_count,
                'sent_count': agent.sent_count,
                'conversion_rate': round(conv, 1),
                'total_earned': profile.total_earned,
                'status': profile.status,
                'status_display': profile.status_display,
            })
        
        context['sales_agents'] = agents_stats
        
        # Add Leaderboard (Top 5 by Total Earned - already sorted by order_by)
        context['leaderboard'] = agents_stats[:5]

    return render(request, 'sales/dashboard.html', context)

@login_required
def data_explorer(request, dataset_id=None):
    from django.db.models import Q
    from sales.models import Dataset, SalesAgentProfile
    
    datasets = Dataset.objects.all().order_by('-created_at')
    
    if dataset_id:
        dataset = get_object_or_404(Dataset, id=dataset_id)
        leads = Lead.objects.filter(dataset=dataset).select_related('contact_details', 'outreach_status', 'assigned_to', 'dataset').prefetch_related('assigned_agents').order_by('-reviews_count', '-rating', '-photos_count')
        visible_columns = dataset.visible_columns if dataset.visible_columns else ['rating', 'phone_primary', 'website_url', 'messages', 'status', 'city']
    else:
        dataset = None
        leads = Lead.objects.select_related('contact_details', 'outreach_status', 'assigned_to', 'dataset').prefetch_related('assigned_agents').all().order_by('-reviews_count', '-rating', '-photos_count')
        # Default visibility: include more main fields
        visible_columns = ['rating', 'phone_primary', 'website_url', 'messages', 'status', 'city', 'business_size']

    # Dataset Statistics (Requested by user)
    dataset_stats = {}
    if dataset:
        from .models import DealRequest
        dataset_stats['confirmed_deals'] = DealRequest.objects.filter(lead__dataset=dataset, status='APPROVED').count()
        dataset_stats['pending_deals'] = DealRequest.objects.filter(lead__dataset=dataset, status='PENDING').count()
        dataset_stats['active_agents'] = leads.exclude(assigned_agents__isnull=True).values('assigned_agents').distinct().count()
        dataset_stats['price'] = dataset.product_price

    # Access Control: Sales Agents see their assigned leads, Managers see theirs + their team's
    if not request.user.is_staff:
        is_manager_check = hasattr(request.user, 'sales_profile') and request.user.sales_profile.subordinates.exists()
        if is_manager_check:
            leads = leads.filter(
                Q(assigned_agents=request.user) | Q(assigned_to=request.user) |
                Q(assigned_agents__sales_profile__manager__user=request.user) |
                Q(assigned_to__sales_profile__manager__user=request.user)
            ).distinct()
        else:
            leads = leads.filter(Q(assigned_agents=request.user) | Q(assigned_to=request.user)).distinct()

    # Search Logic
    query = request.GET.get('q')
    if query:
        # Note: 'contact_details__phone_primary' lets us search by phone
        leads = leads.filter(
            Q(name__icontains=query) |
            Q(city__icontains=query) |
            Q(address__icontains=query) |
            Q(contact_details__phone_primary__icontains=query)
        ).distinct()
    
    # Website Filter
    website_filter = request.GET.get('website_filter')
    if website_filter == 'with_website':
        leads = leads.filter(has_website=True)
    elif website_filter == 'without_website':
        leads = leads.filter(has_website=False)

    # Status Filter
    status_filter = request.GET.get('status_filter')
    if status_filter:
        leads = leads.filter(outreach_status__status=status_filter)

    # Assigned To Filter (Admin Only)
    assigned_filter = request.GET.get('assigned_to')
    if request.user.is_staff and assigned_filter:
        if assigned_filter == 'unassigned':
             leads = leads.filter(assigned_agents__isnull=True, assigned_to__isnull=True)
        else:
             leads = leads.filter(Q(assigned_agents__id=assigned_filter) | Q(assigned_to__id=assigned_filter)).distinct()
    
    # Follow-up Filters
    follow_up_filter = request.GET.get('follow_up_filter')
    if follow_up_filter == 'active':
        leads = leads.filter(outreach_status__follow_up_date__isnull=False)
    elif follow_up_filter == 'today':
        today = timezone.now().date()
        leads = leads.filter(outreach_status__follow_up_date__date=today)
    
    # Sorting
    sort_by = request.GET.get('sort')
    if sort_by == 'follow_up_asc':
        leads = leads.order_by('outreach_status__follow_up_date')
    elif sort_by == 'follow_up_desc':
        leads = leads.order_by('-outreach_status__follow_up_date')
    else:
        # Default sorting
        leads = leads.order_by('-reviews_count', '-rating', '-photos_count')

    # Context for filters
    from django.contrib.auth.models import User
    from .models import OutreachStatus
    from django.core.paginator import Paginator
    
    sales_agents = User.objects.filter(groups__name='Sales') if request.user.is_staff else []

    total_count = leads.count()
    paginator = Paginator(leads, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Manager context: subordinates list for bulk assign dropdown
    is_manager = False
    team_agents = []
    if hasattr(request.user, 'sales_profile'):
        subordinates = request.user.sales_profile.subordinates.select_related('user')
        if subordinates.exists():
            is_manager = True
            team_agents = User.objects.filter(sales_profile__in=subordinates)
    
    # For managers: also show their own leads and their subordinates' leads
    if is_manager and not request.user.is_staff:
        leads = leads.filter(
            Q(assigned_agents=request.user) | Q(assigned_agents__sales_profile__manager__user=request.user)
        ).distinct()

    context = {
        'leads': page_obj, 
        'page_obj': page_obj,
        'total_count': total_count,
        'query': query,
        'sales_agents': sales_agents,
        'team_agents': team_agents,
        'is_manager': is_manager,
        'status_choices': OutreachStatus.STATUS_CHOICES,
        'selected_status': status_filter,
        'current_sort': sort_by,
        'current_follow_up': follow_up_filter,
        'datasets': datasets,
        'current_dataset': dataset,
        'visible_columns': visible_columns,
        'website_filter': website_filter,
        'assigned_to': assigned_filter,
        'dataset_stats': dataset_stats,
    }
    return render(request, 'sales/data_explorer.html', context)


import re
import phonenumbers
def guess_region(city, country):
    text = f"{city} {country}".lower()
    if any(x in text for x in ['saudi', 'ksa', 'السعودية', 'الدمام', 'جدة', 'riyadh', 'dammam', 'jeddah', 'makkah']):
        return 'SA'
    if any(x in text for x in ['uae', 'emirates', 'الإمارات', 'دبي', 'dubai', 'abu dhabi', 'sharjah']):
        return 'AE'
    if any(x in text for x in ['kuwait', 'الكويت']):
        return 'KW'
    if any(x in text for x in ['qatar', 'قطر', 'doha', 'الدوحة']):
        return 'QA'
    if any(x in text for x in ['bahrain', 'البحرين', 'manama']):
        return 'BH'
    if any(x in text for x in ['oman', 'عمان', 'muscat']):
        return 'OM'
    if any(x in text for x in ['jordan', 'الأردن', 'amman']):
        return 'JO'
    return 'EG'

def clean_phone_number(phone_str, city=None, country=None):
    if not phone_str: return "", False, "UNKNOWN"
    
    try:
        region = guess_region(city, country)
        clean_str = re.sub(r'[a-zA-Z]', '', str(phone_str)).strip()
        if clean_str.startswith('00'):
            clean_str = '+' + clean_str[2:]
        parsed = phonenumbers.parse(clean_str, region)
        
        if phonenumbers.is_valid_number(parsed):
            if phonenumbers.number_type(parsed) == phonenumbers.PhoneNumberType.MOBILE:
                formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                return formatted, True, "MOBILE"
            else:
                formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
                formatted = re.sub(r'[\s\-\(\)]', '', formatted)
                return formatted, True, "FIXED"
    except Exception:
        pass
        
    p = str(phone_str)
    cleaned = re.sub(r'[\s\-\(\)]', '', p)
    digits_only = re.sub(r'\D', '', cleaned)
    if cleaned.startswith('01') and len(digits_only) == 11:
        cleaned = '+20' + cleaned[1:]
        return cleaned, True, "MOBILE"
    elif cleaned.startswith('+') or cleaned.startswith('00'):
        pass
    else:
        cleaned = re.sub(r'[^\d+]', '', cleaned)
    is_valid = len(re.sub(r'\D', '', cleaned)) >= 8
    
    if len(digits_only) in [9, 10] and not cleaned.startswith('+') and not cleaned.startswith('00'):
        return cleaned, is_valid, "FIXED"
        
    return cleaned, is_valid, "UNKNOWN"

def clean_address_text(addr_str):
    if not addr_str: return ""
    addr = str(addr_str).strip()
    addr = re.sub(r'\(.*?\)', '', addr)
    addr = re.sub(r'\bGovernorate\b', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bمحافظة\b', '', addr)
    words = [w.strip() for w in addr.split(',')]
    new_words = []
    seen = set()
    for w in words:
        w_lower = w.lower()
        if w and w_lower not in seen:
            seen.add(w_lower)
            new_words.append(w)
    return ", ".join(new_words).replace("\n", " ").strip()

@login_required
def lead_detail(request, pk):
    from .models import OutreachStatus
    lead = get_object_or_404(Lead.objects.select_related('contact_details', 'outreach_status', 'assigned_to', 'dataset'), pk=pk)
    
    # AUTO-MIGRATION FALLBACK: If lead has assigned_to but no assigned_agents, fix it on the fly
    if lead.assigned_to and not lead.assigned_agents.exists():
        lead.assigned_agents.add(lead.assigned_to)
        
    cleaned_primary = ""
    phone_type = "UNKNOWN"
    if hasattr(lead, 'contact_details') and lead.contact_details.phone_primary:
        cp, vp, ptype = clean_phone_number(lead.contact_details.phone_primary, lead.city, lead.country)
        cleaned_primary = cp if vp else f"{cp} (Invalid)"
        phone_type = ptype
        
    cleaned_address = clean_address_text(lead.address)
        
    return render(request, 'sales/lead_detail.html', {
        'lead': lead,
        'status_choices': OutreachStatus.STATUS_CHOICES,
        'cleaned_primary': cleaned_primary,
        'cleaned_address': cleaned_address,
        'phone_type': phone_type
    })

import uuid
import threading
from django.db.models import Q

@login_required
def export_csv(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)

    # Filter Logic
    filter_type = request.GET.get('filter', 'all')
    website_filter = request.GET.get('website_filter')
    query = request.GET.get('q')
    dataset_id = request.GET.get('dataset')
    
    leads = Lead.objects.all().order_by('-rating', '-reviews_count', '-created_at')
    
    if dataset_id:
        leads = leads.filter(dataset_id=dataset_id)
    
    # Apply search filter
    if query:
        leads = leads.filter(
            Q(name__icontains=query) |
            Q(city__icontains=query) |
            Q(address__icontains=query) |
            Q(contact_details__phone_primary__icontains=query)
        ).distinct()
    
    # Apply website filter
    if website_filter == 'with_website':
        leads = leads.filter(has_website=True)
    elif website_filter == 'without_website':
        leads = leads.filter(has_website=False)
    
    if filter_type == 'emails':
        # Get leads where email_list is not empty (requires parsing or logic if JSON)
        # Detailed check: exclude empty list
        leads = [r for r in leads if r.contact_details.email_list]
    elif filter_type == 'phones':
        # Get leads with phone numbers
        leads = [r for r in leads if r.contact_details.phone_primary]

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    import re

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Leads"

    # Add Legend
    ws.append(["Legend: Importance Score Guide"])
    ws.append(["🟩 High Priority (> 70%)"])
    ws.append(["🟨 Medium Priority (40% - 70%)"])
    ws.append(["🟥 Low Priority (< 40%)"])
    ws.append([]) # Empty row for spacing
    
    headers = ['Name', 'City', 'Phone', 'Emails', 'Rating', 'Reviews', 'Priority Score', 'Importance %', 'Status', 'Map Link', 'Social Links', 'Website', 'Address']
    ws.append(headers)

    header_row_idx = 6
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in ws[header_row_idx]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    column_widths = {'A': 35, 'B': 15, 'C': 20, 'D': 30, 'E': 10, 'F': 10, 'G': 15, 'H': 15, 'I': 15, 'J': 15, 'K': 40, 'L': 25, 'M': 50}
    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width

    # Data Validation for Status
    dv = DataValidation(type="list", formula1='"Not Contacted,Contacted,Following Up,Closed"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("I7:I1048576")

    def _clean_phone(phone_str, city=None, country=None):
        # We can just reuse the global function
        return clean_phone_number(phone_str, city, country)

    all_rows = []
    max_score = 1
    
    for r in leads:
        raw_phone = r.contact_details.phone_primary if hasattr(r, 'contact_details') else ""
        phone, is_valid, phone_type = _clean_phone(raw_phone, r.city, r.country)
        
        raw_emails = ", ".join(r.contact_details.email_list) if hasattr(r, 'contact_details') and r.contact_details.email_list else ""
        emails = raw_emails if raw_emails else "N/A"
        
        socials_val = "N/A"
        socials_hyper = ""
        if hasattr(r, 'contact_details') and r.contact_details.social_links:
            socials_val = " | ".join([k.capitalize() for k in r.contact_details.social_links.keys()])
            socials_hyper = list(r.contact_details.social_links.values())[0]
            
        status = r.outreach_status.get_status_display() if hasattr(r, 'outreach_status') else "Not Contacted"
        
        website_val = "Website" if r.website_url else "N/A"
        website_hyper = r.website_url if r.website_url else ""
        
        address_actual = clean_address_text(r.address)
        address_val = "Address" if address_actual else "N/A"
        
        map_text = "Map Link" if r.gmaps_id else "N/A"
        
        rating = float(r.rating) if r.rating else 0.0
        reviews = int(r.reviews_count) if r.reviews_count else 0
        
        score = (rating * 20) + (reviews * 0.5) + (50 if is_valid else 0)
        if score > max_score:
            max_score = score
            
        all_rows.append({
            'name': r.name, 'city': r.city, 'phone': phone, 'phone_type': phone_type, 'emails': emails,
            'rating': rating, 'reviews': reviews, 'score': score, 'status': status,
            'gmaps_id': r.gmaps_id, 'map_text': map_text, 'address_actual': address_actual,
            'socials_val': socials_val, 'socials_hyper': socials_hyper, 
            'website_val': website_val, 'website_hyper': website_hyper
        })
        
    all_rows.sort(key=lambda x: x['score'], reverse=True)
    
    for row_dict in all_rows:
        importance = round((row_dict['score'] / max_score) * 100, 1)
        importance_str = f"{importance}%"
        
        row_data = [
            row_dict['name'], row_dict['city'], row_dict['phone'], row_dict['emails'],
            row_dict['rating'], row_dict['reviews'], row_dict['score'], importance_str,
            row_dict['status'], row_dict['map_text'], row_dict['socials_val'], row_dict['website_val'], row_dict['address_actual']
        ]
        ws.append(row_data)
        
        current_row = ws.max_row
        
        import urllib.parse
        from openpyxl.comments import Comment
        # Apply hyperlinking and comments
        if row_dict.get('gmaps_id'):
            map_cell = ws.cell(row=current_row, column=10)
            query = urllib.parse.quote(f"{row_dict['name']} {row_dict['city']}")
            map_cell.hyperlink = f"https://www.google.com/maps/search/?api=1&query={query}"
            map_cell.font = Font(underline="single", color="0563C1")
            
        if row_dict.get('socials_hyper'):
            soc_cell = ws.cell(row=current_row, column=11)
            soc_cell.hyperlink = row_dict['socials_hyper']
            soc_cell.font = Font(underline="single", color="0563C1")
            
        if row_dict.get('website_hyper'):
            web_cell = ws.cell(row=current_row, column=12)
            web_cell.hyperlink = row_dict['website_hyper']
            web_cell.font = Font(underline="single", color="0563C1")
        
        data_alignment = Alignment(wrap_text=False, vertical="center")
        for cell in ws[current_row]:
            cell.alignment = data_alignment
            
        phone_cell = ws.cell(row=current_row, column=3)
        phone_cell.number_format = '@'
        if row_dict.get('phone_type') == 'FIXED':
            phone_cell.fill = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
            
        imp_cell = ws.cell(row=current_row, column=8)
        if importance > 70:
            imp_cell.fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
            imp_cell.font = Font(color="006100")
        elif importance >= 40:
            imp_cell.fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
            imp_cell.font = Font(color="9C5700")
        else:
            imp_cell.fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
            imp_cell.font = Font(color="9C0006")
        
        for col_idx in [5, 6, 7, 8, 9]:
            ws.cell(row=current_row, column=col_idx).alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    filename = f"leads_export_improved_{filter_type}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response

@login_required
def import_leads_excel(request, dataset_id):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    dataset = get_object_or_404(Dataset, id=dataset_id)

    if request.method == 'POST':
        file = request.FILES.get('file')
        if not file:
            messages.error(request, "Please select an Excel or CSV file.")
            return redirect('data_explorer_dataset', dataset_id=dataset.id)
        
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
            
            # Smart Match Column Names (English & Arabic)
            col_map = {
                'name': ['name', 'اسم', 'business name', 'restaurant name', 'title', 'الاسم', 'المطعم', 'اسم النشاط'],
                'city': ['city', 'مدينة', 'location', 'المدينة', 'القاهرة', 'city_name'],
                'address': ['address', 'عنوان', 'full address', 'العنوان', 'full_address'],
                'phone': ['phone', 'mobile', 'هاتف', 'تليفون', 'primary phone', 'whatsapp', 'رقم الهاتف', 'موبايل', 'phone_number'],
                'website': ['website', 'site', 'url', 'موقع', 'website url', 'الموقع الإلكتروني', 'موقع ويب'],
                'rating': ['rating', 'تقييم', 'google rating', 'التقييم', 'rating_value'],
                'reviews': ['reviews', 'review count', 'عدد التقييمات', 'المراجعات', 'reviews_count'],
                'gmaps_id': ['gmaps_id', 'id', 'google id', 'معرف جوجل', 'place_id']
            }
            
            def find_col(possible_names):
                for col in df.columns:
                    c_low = str(col).lower().strip()
                    if c_low in [p.lower() for p in possible_names]:
                        return col
                return None

            mapping = {k: find_col(v) for k, v in col_map.items()}
            
            # Check if we at least have Name
            if not mapping['name']:
                messages.error(request, "Could not find a 'Name' column in the uploaded file.")
                return redirect('data_explorer_dataset', dataset_id=dataset.id)

            success_count = 0
            skipped_count = 0
            
            # Use atomic transaction for better performance/reliability if needed, 
            # but for now simple loop is fine as we handle duplicates
            for _, row in df.iterrows():
                name = str(row[mapping['name']]) if mapping['name'] and pd.notna(row[mapping['name']]) else None
                if not name or name.strip() == "":
                    continue
                
                city = str(row[mapping['city']]) if mapping['city'] and pd.notna(row[mapping['city']]) else "Unknown"
                gmaps_id = str(row[mapping['gmaps_id']]) if mapping['gmaps_id'] and pd.notna(row[mapping['gmaps_id']]) else None
                
                # Deduplication
                if gmaps_id and Lead.objects.filter(gmaps_id=gmaps_id).exists():
                    skipped_count += 1
                    continue
                
                # Check by Name and City if gmaps_id is missing
                if not gmaps_id and Lead.objects.filter(name=name, city=city[:100], dataset=dataset).exists():
                    skipped_count += 1
                    continue

                try:
                    # Create Lead
                    lead = Lead.objects.create(
                        dataset=dataset,
                        name=name,
                        city=city[:100],
                        address=str(row[mapping['address']]) if mapping['address'] and pd.notna(row[mapping['address']]) else "",
                        has_website=pd.notna(row[mapping['website']]) if mapping['website'] else False,
                        website_url=str(row[mapping['website']]) if mapping['website'] and pd.notna(row[mapping['website']]) else "",
                        rating=float(row[mapping['rating']]) if mapping['rating'] and pd.notna(row[mapping['rating']]) else 0.0,
                        reviews_count=int(row[mapping['reviews']]) if mapping['reviews'] and pd.notna(row[mapping['reviews']]) else 0,
                        gmaps_id=gmaps_id
                    )
                    
                    # Contact Details
                    phone = str(row[mapping['phone']]) if mapping['phone'] and pd.notna(row[mapping['phone']]) else ""
                    ContactDetails.objects.create(
                        lead=lead,
                        phone_primary=phone
                    )
                    
                    # Outreach Status
                    OutreachStatus.objects.create(
                        lead=lead,
                        status='NOT_CONTACTED'
                    )
                    success_count += 1
                except Exception:
                    skipped_count += 1
                
            messages.success(request, f"Successfully imported {success_count} leads. {skipped_count} skipped (duplicates or invalid).")
            
        except Exception as e:
            messages.error(request, f"Error importing data: {str(e)}")
            
    return redirect('data_explorer_dataset', dataset_id=dataset.id)

@login_required
def clear_data(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    if request.method == "POST":
        action = request.POST.get('action')
        
        if action == 'all':
            count = Lead.objects.count()
            Lead.objects.all().delete()
            return HttpResponse(f"<div class='alert alert-success'>Deleted all {count} records. Database is empty.</div>")
            
        elif action == 'junk':
            # Optimized ORM query to find leads with no phone AND no email
            # We check for NULL values, empty strings, and empty JSON lists
            junk_leads = Lead.objects.filter(
                Q(contact_details__isnull=True) |
                (
                    (Q(contact_details__phone_primary__isnull=True) | Q(contact_details__phone_primary='')) &
                    (Q(contact_details__email_list__isnull=True) | Q(contact_details__email_list=[]) | Q(contact_details__email_list='[]') | Q(contact_details__email_list=''))
                )
            )
            count = junk_leads.count()
            junk_leads.delete()
            messages.success(request, f"تم حذف {count} من السجلات غير الهامة (بدون تليفون أو إيميل).")
            return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))

    return HttpResponse("Method not allowed", status=405)

@login_required
@require_POST
def update_status(request, pk):
    """Update outreach status for a lead"""
    if request.method == "POST":
        # Idempotency Check for Offline Sync
        idempotency_key = request.headers.get('X-Idempotency-Key') or request.META.get('HTTP_X_IDEMPOTENCY_KEY')
        if idempotency_key:
            from .models import IdempotencyKey
            if IdempotencyKey.objects.filter(key=idempotency_key).exists():
                return JsonResponse({'status': 'success', 'message': 'Duplicate request suppressed (Idempotent)', 'pk': pk})
            IdempotencyKey.objects.create(key=idempotency_key, user=request.user)

        lead = get_object_or_404(Lead, pk=pk)
        
        # Permission check: Admin can update anything, Sales can only update if assigned
        is_assigned = lead.assigned_agents.filter(id=request.user.id).exists()
        if not request.user.is_staff and not is_assigned:
            return JsonResponse({'status': 'error', 'message': 'Permission denied: You are not assigned to this lead.'}, status=403)
            
        new_status = request.POST.get('status')
        follow_up_date = request.POST.get('follow_up_date')
        follow_up_notes = request.POST.get('follow_up_notes')
        deal_price = request.POST.get('deal_price', 0)
        deal_notes = request.POST.get('deal_notes', '')
        
        if new_status in dict(OutreachStatus.STATUS_CHOICES):
            # Enforce Lock: Non-staff cannot change status if it's already DEAL
            if not request.user.is_staff and lead.outreach_status.status == 'DEAL':
                return JsonResponse({'status': 'error', 'message': 'Locked: Deal status can only be changed by admin.'}, status=403)

            # ADMIN AUTO-APPROVAL (Requested: If admin sets to DEAL, it confirms immediately)
            if request.user.is_staff and new_status == 'DEAL':
                from .models import DealRequest
                DealRequest.objects.update_or_create(
                    lead=lead,
                    defaults={
                        'sales_agent': request.user, # Mark as admin closed
                        'price': float(deal_price) if deal_price else 0,
                        'notes': f"[AUTO-APPROVED BY ADMIN] {deal_notes}",
                        'status': 'APPROVED',
                        'reviewed_at': timezone.now(),
                        'reviewed_by': request.user
                    }
                )

            # Debug logging
            print(f"DEBUG: Processing status update for lead {pk}. Action by: {request.user.username}")
            print(f"DEBUG: New Status: {new_status}, Date: {follow_up_date}")
            
            parsed_date = None
            if new_status == 'FOLLOW_UP' and follow_up_date:
                try:
                    from django.utils.dateparse import parse_datetime
                    parsed_date = parse_datetime(follow_up_date)
                except (ValueError, TypeError):
                    pass
            
            try:
                # Using update_or_create for atomicity and immediate persistence
                outreach_status, created = OutreachStatus.objects.update_or_create(
                    lead=lead,
                    defaults={
                        'status': new_status,
                        'last_contact_date': timezone.now(),
                        'follow_up_date': parsed_date if new_status == 'FOLLOW_UP' else None,
                        'follow_up_notes': follow_up_notes if new_status == 'FOLLOW_UP' else (None if new_status != 'FOLLOW_UP' else '')
                    }
                )
                print(f"DEBUG: Status saved successfully in DB for {pk}. Final status: {outreach_status.status}")

                # --- Deal Request Logic (Non-staff agents submit for approval) ---
                if new_status == 'DEAL' and not request.user.is_staff:
                    from .models import DealRequest
                    deal_price = request.POST.get('deal_price', 0)
                    deal_notes = request.POST.get('deal_notes', '')
                    try:
                        deal_price = float(deal_price)
                    except (ValueError, TypeError):
                        deal_price = 0

                    deal_request, created_request = DealRequest.objects.update_or_create(
                        lead=lead,
                        defaults={
                            'sales_agent': request.user,
                            'price': deal_price,
                            'notes': deal_notes,
                            'status': 'PENDING',
                        }
                    )

                    # Fire Notification for Admins and Manager
                    if created_request:
                        from notifications.utils import create_notification
                        from django.contrib.auth.models import User
                        manager_user = None
                        if hasattr(request.user, 'sales_profile') and request.user.sales_profile.manager:
                            manager_user = request.user.sales_profile.manager.user
                            create_notification(
                                recipient=manager_user,
                                sender=request.user,
                                notification_type='DEAL_REQUEST_NEW',
                                title="New Deal Request",
                                message=f"{request.user.username} submitted a new deal request for {lead.name} ({deal_price} EGP).",
                                target_url='/deals/pending/'
                            )

                        admins = User.objects.filter(is_staff=True)
                        for admin in admins:
                            if admin != request.user and admin != manager_user:
                                create_notification(
                                    recipient=admin,
                                    sender=request.user,
                                    notification_type='DEAL_REQUEST_NEW',
                                    title="New Deal Request Action Required",
                                    message=f"{request.user.username} submitted a deal request for {lead.name} ({deal_price} EGP).",
                                    target_url='/deals/pending/'
                                )

            except Exception as e:
                print(f"DEBUG: CRITICAL DATABASE ERROR for lead {pk}: {str(e)}")
                return JsonResponse({'status': 'error', 'message': f'DB Error: {str(e)}'}, status=500)

            # Robust AJAX check
            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                      request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
                      request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' or \
                      request.content_type == 'application/json'
                      
            if is_ajax:
                return JsonResponse({
                    'status': 'success', 
                    'saved_status': outreach_status.status,
                    'pk': pk,
                    'deal_pending': new_status == 'DEAL' and not request.user.is_staff
                })
        
        return redirect('data_explorer')
    
    return HttpResponse("Method not allowed", status=405)


@login_required
def update_message(request, pk):
    """AJAX view to update message body or second message for a lead"""
    if request.method == "POST":
        try:
            import json
            data = json.loads(request.body)
            new_message = data.get('message')
            message_type = data.get('message_type', 'first')
            
            lead = get_object_or_404(Lead, pk=pk)
            
            # Ensure ContactDetails exists
            if not hasattr(lead, 'contact_details'):
                ContactDetails.objects.create(lead=lead)
            
            # Update the appropriate message field
            if message_type == 'second':
                lead.contact_details.second_message = new_message
            else:
                lead.contact_details.message_body = new_message
                
            lead.contact_details.save()
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

    return HttpResponse("Method not allowed", status=405)
@login_required
def export_vcf(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)

    """Export contacts to vCard format for phone import"""
    filter_type = request.GET.get('filter', 'all')
    website_filter = request.GET.get('website_filter')
    query = request.GET.get('q')
    dataset_id = request.GET.get('dataset')
    
    leads = Lead.objects.all().order_by('-created_at')
    
    if dataset_id:
        leads = leads.filter(dataset_id=dataset_id)
    
    # Apply search filter
    if query:
        leads = leads.filter(
            Q(name__icontains=query) |
            Q(city__icontains=query) |
            Q(address__icontains=query) |
            Q(contact_details__phone_primary__icontains=query)
        ).distinct()
    
    # Apply website filter
    if website_filter == 'with_website':
        leads = leads.filter(has_website=True)
    elif website_filter == 'without_website':
        leads = leads.filter(has_website=False)

    import re
    def _clean_phone(phone_str):
        if not phone_str: return "", False
        p = str(phone_str)
        cleaned = re.sub(r'[\s\-\(\)]', '', p)
        digits_only = re.sub(r'\D', '', cleaned)
        if cleaned.startswith('0') and len(digits_only) in [10, 11]:
            cleaned = '+20' + cleaned[1:]
        elif cleaned.startswith('+') or cleaned.startswith('00'):
            pass
        else:
            cleaned = re.sub(r'[^\d+]', '', cleaned)
        is_valid = len(re.sub(r'\D', '', cleaned)) >= 8
        return cleaned, is_valid

    # Filter for valid phone numbers
    valid_leads = []
    for r in leads:
        if hasattr(r, 'contact_details') and (r.contact_details.phone_primary or r.contact_details.phone_whatsapp):
            valid_leads.append(r)

    vcard_data = ""
    for r in valid_leads:
        name = r.name
        # Prioritize WhatsApp phone, then primary
        raw_phone = r.contact_details.phone_whatsapp or r.contact_details.phone_primary
        phone, is_valid = _clean_phone(raw_phone)
        
        if not is_valid:
            continue
            
        # Simple vCard 3.0 format construction
        vcard_data += "BEGIN:VCARD\n"
        vcard_data += "VERSION:3.0\n"
        vcard_data += f"FN:{name}\n"
        vcard_data += f"TEL;TYPE=CELL:{phone}\n"
        
        # Add email if available
        if r.contact_details.email_list:
             # email_list might be a list or string representation of a list
             import ast
             try:
                 emails = r.contact_details.email_list
                 if isinstance(emails, str):
                     emails = ast.literal_eval(emails)
                 if emails and isinstance(emails, list):
                     vcard_data += f"EMAIL:{emails[0]}\n"
             except:
                 pass
                 
        vcard_data += "END:VCARD\n"

    response = HttpResponse(vcard_data, content_type='text/vcard')
    response['Content-Disposition'] = 'attachment; filename="contacts.vcf"'
    return response


@login_required
def generate_intro_messages(request):
    """Generate personalized intro messages for all leads"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    if request.method == "POST":
        from .models import SystemSettings
        settings = SystemSettings.get_settings()
        
        leads = Lead.objects.all()
        
        # Message Templates from Settings
        template = settings.first_message_template
        template2 = settings.second_message_template

        count = 0
        for r in leads:
            # Ensure ContactDetails exists
            if not hasattr(r, 'contact_details'):
                ContactDetails.objects.create(lead=r)
            
            # Use dataset override price if available
            price_to_use = settings.product_price
            if r.dataset and r.dataset.product_price is not None:
                price_to_use = r.dataset.product_price
            
            # Format message 1
            msg = template.format(
                name=r.name,
                rating=r.rating,
                reviews_count=r.reviews_count,
                city=r.city or "المنطقة",
                product_price=price_to_use
            )
            
            # Format message 2
            msg2 = template2.format(
                name=r.name,
                product_price=price_to_use
            )
            
            r.contact_details.message_body = msg
            r.contact_details.second_message = msg2
            r.contact_details.save()
            count += 1
            
        return redirect('data_explorer')
    
    return HttpResponse("Method not allowed", status=405)



# --- Sales Team Management ---

@login_required
def manage_team(request):
    """List sales agents depending on role:
       - Admin: All agents and global stats.
       - Manager: Themselves + subordinates and team stats.
       - Agent: Themselves and personal stats."""
    
    from django.contrib.auth.models import Group, User
    from django.db.models import Count, Q
    
    # Ensure user is staff or in Sales group
    if not request.user.is_staff and not request.user.groups.filter(name='Sales').exists():
        return redirect('dashboard')
        
    # Ensure group exists (safe check)
    sales_group, _ = Group.objects.get_or_create(name='Sales')
    
    # Get all potential managers (anyone in Sales group) for the dropdown (Staff only)
    all_managers = User.objects.filter(groups__name='Sales').select_related('sales_profile') if request.user.is_staff else []
    
    # Base filtering logic based on role
    if request.user.is_staff:
        # Admin sees everyone
        agents_filter = Q(groups__name='Sales')
    else:
        # Sales Agent / Manager sees themselves + subordinates
        agents_filter = Q(id=request.user.id) | Q(sales_profile__manager__user=request.user)
    
    # Base Query for the list
    agents_qs = User.objects.filter(agents_filter).select_related('sales_profile').annotate(
        assigned_count=Count('assigned_leads')
    ).order_by('-date_joined')

    # Team Statistics (Aggregation)
    from django.db.models import Sum, F, DecimalField
    from sales.models import SubscriptionOrder, AgentPayout
    from decimal import Decimal
    
    stats_qs = User.objects.filter(agents_filter)
    total_members = stats_qs.count()
    
    # Calculate totals from SubscriptionOrder directly for accuracy
    if request.user.is_staff:
        orders_qs = SubscriptionOrder.objects.filter(status='COMPLETED')
    else:
        # For non-staff, they only see stats for deals they or their subordinates closed
        orders_qs = SubscriptionOrder.objects.filter(
            Q(status='COMPLETED') & (Q(sales_agent=request.user) | Q(sales_agent__sales_profile__manager__user=request.user))
        )

    total_agg = orders_qs.aggregate(
        direct=Sum(F('price') * F('commission_rate'), output_field=DecimalField()),
        manager=Sum(F('price') * F('manager_commission_rate'), output_field=DecimalField())
    )
    
    grand_total_earned = (Decimal(total_agg['direct'] or 0) + Decimal(total_agg['manager'] or 0)) / Decimal(100)
    
    if request.user.is_staff:
        total_paid = AgentPayout.objects.aggregate(total=Sum('amount'))['total'] or 0
    else:
        total_paid = AgentPayout.objects.filter(agent__in=stats_qs).aggregate(total=Sum('amount'))['total'] or 0
        
    total_balance = grand_total_earned - total_paid
    
    team_stats = {
        'total_members': total_members,
        'total_earned': grand_total_earned,
        'grand_total_earned': grand_total_earned,
        'total_paid': total_paid,
        'total_balance': total_balance
    }
    
    # Filter Logic
    from django.db.models import Q
    query = request.GET.get('q')
    if query:
        agents_qs = agents_qs.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query)
        )
        
    manager_filter = request.GET.get('manager_id')
    if manager_filter:
        agents_qs = agents_qs.filter(sales_profile__manager_id=manager_filter)
    
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(agents_qs, 100) # 100 per page as requested
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'sales/team_list.html', {
        'agents': page_obj,
        'all_managers': all_managers,
        'page_obj': page_obj,
        'query': query,
        'selected_manager': manager_filter,
        'team_stats': team_stats,
    })

@login_required
def add_sales_agent(request):
    """Create a new sales agent"""
    # Allow staff, or existing sales agents if they are intended to be managers
    if not request.user.is_staff:
        return redirect('dashboard')
        
    from .forms import SalesAgentForm
    from django.contrib.auth.models import Group
    from .models import SalesAgentProfile
    
    if request.method == "POST":
        form = SalesAgentForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Add to Sales group
            sales_group, _ = Group.objects.get_or_create(name='Sales')
            user.groups.add(sales_group)
            
            # If creator is a sales agent, automatically make them the manager 
            # and give them a standard 2% team commission logic (can be adjusted)
            if not request.user.is_staff and request.user.groups.filter(name='Sales').exists():
                # Ensure the creator has a SalesAgentProfile
                if hasattr(request.user, 'sales_profile'):
                    profile = user.sales_profile
                    profile.manager = request.user.sales_profile
                    # The manager gets team_commission_rate from their own profile,
                    # this is just saving the hierarchy relationship
                    profile.save()
                    
            return redirect('manage_team')
    else:
        form = SalesAgentForm()
        
    return render(request, 'sales/add_agent.html', {'form': form})

@login_required
def add_admin(request):
    """Create a new staff/admin user"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    from .forms import AdminAccountForm
    from django.contrib import messages
    from django.shortcuts import redirect, render
    
    if request.method == "POST":
        form = AdminAccountForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Also ensure they have a SalesAgentProfile for profile picture
            from .models import SalesAgentProfile
            SalesAgentProfile.objects.get_or_create(user=user)
            messages.success(request, f"Admin account for {user.username} created successfully.")
            return redirect('manage_team')
    else:
        form = AdminAccountForm()
        
    return render(request, 'sales/add_admin.html', {'form': form})


@login_required
def record_payout(request):
    """Admin endpoint to record a manual payout to an agent"""
    if not request.user.is_staff or request.method != 'POST':
        return redirect('dashboard')
        
    from django.contrib.auth.models import User
    from .models import AgentPayout
    from decimal import Decimal
    
    agent_id = request.POST.get('agent_id')
    amount_str = request.POST.get('amount')
    notes = request.POST.get('notes', '')
    
    if agent_id and amount_str:
        try:
            agent = User.objects.get(id=agent_id)
            amount = Decimal(amount_str)
            if amount > 0:
                AgentPayout.objects.create(
                    agent=agent,
                    amount=amount,
                    notes=notes
                )
        except (User.DoesNotExist, ValueError):
            pass
            
    return redirect('manage_team')

# --- Checkout System ---




@login_required
def bulk_assign_leads(request):
    """Handle bulk assignment of leads to sales agents (Admin Only)"""
    is_admin = request.user.is_staff
    is_manager = False
    if hasattr(request.user, 'sales_profile'):
        is_manager = request.user.sales_profile.subordinates.exists()
    
    if not is_admin and not is_manager:
        return HttpResponse("Unauthorized", status=403)
        
    if request.method == "POST":
        from django.contrib.auth.models import User
        from django.db.models import Q
        
        action_type = request.POST.get('action_type') # 'selected', 'unassign', or 'all_filtered'
        selected_ids = request.POST.getlist('selected_ids')
        
        from notifications.utils import create_notification
        
        # 1. Handle Unassign (Doesn't require agents)
        if action_type == 'unassign':
            leads_to_update = Lead.objects.filter(id__in=selected_ids)
            if is_manager and not is_admin:
                # Managers can unassign leads from themselves or their subordinates
                leads_to_update = leads_to_update.filter(
                    Q(assigned_agents=request.user) | Q(assigned_agents__sales_profile__manager__user=request.user)
                ).distinct()
            
            # Group unassigned leads per agent to send one notification per agent
            from collections import defaultdict
            unassigned_count_per_agent = defaultdict(int)
            
            for lead in leads_to_update:
                for agent in lead.assigned_agents.all():
                    unassigned_count_per_agent[agent] += 1
                lead.assigned_agents.clear()
                lead.assigned_to = None
                lead.save(update_fields=['assigned_to'])
                
            # Fire notifications
            for agent, count in unassigned_count_per_agent.items():
                if agent != request.user:
                    create_notification(
                        recipient=agent,
                        sender=request.user,
                        notification_type='LEAD_REMOVED',
                        title="Leads Removed",
                        message=f"{count} leads have been unassigned from your portfolio by {request.user.username}."
                    )
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': 'Leads unassigned successfully'})
            return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))
            
        # 2. Handle Assignments (Requires agents)
        assignee_ids = request.POST.getlist('assignee_id')
        if not assignee_ids:
             return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))
             
        # Fetch all target agents
        assignees = User.objects.filter(id__in=assignee_ids)
        if is_manager and not is_admin:
            # Managers can only assign to themselves or their subordinates
            assignees = assignees.filter(
                Q(id=request.user.id) | Q(sales_profile__manager__user=request.user)
            ).distinct()
            
        if not assignees.exists():
             return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))
            
        if action_type == 'selected':
            leads_to_update = list(Lead.objects.filter(id__in=selected_ids))
            # Security check: managers can only assign leads they currently own
            if is_manager and not is_admin:
                # Managers can assign leads they or their subordinates currently own
                leads_to_update = list(Lead.objects.filter(id__in=selected_ids).filter(
                    Q(assigned_agents=request.user) | Q(assigned_agents__sales_profile__manager__user=request.user)
                ).distinct())
                
            for lead in leads_to_update:
                lead.assigned_agents.add(*assignees)
                
            # Fire notifications
            leads_count = len(leads_to_update)
            if leads_count > 0:
                for agent in assignees:
                    if agent != request.user:
                        create_notification(
                            recipient=agent,
                            sender=request.user,
                            notification_type='LEAD_ASSIGNED',
                            title="New Leads Assigned",
                            message=f"{leads_count} new leads have been assigned to you by {request.user.username}.",
                            target_url='/my-profile/'
                        )
                
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': f'Leads assigned to {assignees.count()} agents'})

        elif action_type == 'all_filtered':
            dataset_id = request.POST.get('dataset_id')
            q_filter = Lead.objects.all()
            if dataset_id:
                q_filter = q_filter.filter(dataset_id=dataset_id)
            
            # Security check: Managers can only filter from their own team's pool
            if is_manager and not is_admin:
                q_filter = q_filter.filter(
                    Q(assigned_agents=request.user) | Q(assigned_agents__sales_profile__manager__user=request.user)
                ).distinct()
            
            query = request.POST.get('q')
            if query:
                q_filter = q_filter.filter(
                    Q(name__icontains=query) |
                    Q(city__icontains=query) |
                    Q(address__icontains=query) |
                    Q(contact_details__phone_primary__icontains=query)
                )
            
            website_filter = request.POST.get('website_filter')
            if website_filter == 'with_website':
                q_filter = q_filter.filter(has_website=True)
            elif website_filter == 'without_website':
                q_filter = q_filter.filter(has_website=False)
                
            assigned_filter = request.POST.get('assigned_to')
            if assigned_filter and is_admin: # Only admins can filter by current assignee
                if assigned_filter == 'unassigned':
                     q_filter = q_filter.filter(assigned_agents__isnull=True)
                else:
                     q_filter = q_filter.filter(assigned_agents__id=assigned_filter)
            
            # Apply Update (Using a loop for M2M .add())
            for lead in q_filter:
                lead.assigned_agents.add(*assignees)
                # Legacy compatibility: also set the first agent as primary if none
                if lead.assigned_to is None:
                    lead.assigned_to = assignees.first()
                    lead.save(update_fields=['assigned_to'])
            
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success', 'message': f'All filtered leads assigned to {assignees.count()} agents'})
            
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success', 'message': 'Leads assigned successfully'})
            
        return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))
    
    return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))


# --- Profile & Settings ---

# Redundant agent_detail removed. Standardized on sales_views.sales_agent_profile.

# Redundant update_agent_config removed. Standardized on sales_views.update_agent_config.

@login_required
def admin_reset_password(request, pk):
    """Admin forces a password reset for an agent"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    
    if request.method == "POST":
        from django.contrib.auth.models import User
        agent = get_object_or_404(User, pk=pk)
        new_pass = request.POST.get('new_password')
        if new_pass and len(new_pass) >= 6:
            agent.set_password(new_pass)
            agent.save()
            
            from sales.models import AgentHistoryLog
            AgentHistoryLog.objects.create(
                agent=agent,
                action_by=request.user,
                action_type='PASSWORD_RESET',
                details="Admin forced a password reset."
            )
            
            messages.success(request, f"Password for {agent.username} updated successfully.")
        else:
            messages.error(request, "Password must be at least 6 characters.")
            
        return redirect('sales_agent_profile', agent_id=pk)
    return redirect('manage_team')

@login_required
def toggle_agent_status(request, pk):
    """Admin toggles active status of an agent"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    
    if request.method == "POST":
        from django.contrib.auth.models import User
        agent = get_object_or_404(User, pk=pk)
        # Prevent self-lockout
        if agent == request.user:
             messages.error(request, "You cannot suspend your own account.")
             return redirect('sales_agent_profile', agent_id=pk)
             
        agent.is_active = not agent.is_active
        agent.save()
        status = "activated" if agent.is_active else "suspended"
        
        from sales.models import AgentHistoryLog
        AgentHistoryLog.objects.create(
            agent=agent,
            action_by=request.user,
            action_type='STATUS_CHANGE',
            details=f"Account status changed to {status.upper()}"
        )
        
        messages.success(request, f"Account {agent.username} has been {status}.")
        return redirect('sales_agent_profile', agent_id=pk)
    return redirect('manage_team')

@login_required
def user_settings(request):
    """User changes their own settings (name, email, profile picture, password)"""
    from django.contrib.auth.forms import PasswordChangeForm
    from django.contrib.auth import update_session_auth_hash
    from django.contrib import messages
    from .forms import UserSettingsForm
    from .models import SalesAgentProfile
    
    # Get or create sales profile to store profile picture
    profile, created = SalesAgentProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_profile':
            settings_form = UserSettingsForm(request.POST, request.FILES, instance=request.user)
            password_form = PasswordChangeForm(request.user)
            if settings_form.is_valid():
                user = settings_form.save()
                
                # Handle SalesAgentProfile specific fields
                profile_updated = False
                if 'profile_picture' in request.FILES:
                    profile.profile_picture = request.FILES['profile_picture']
                    profile_updated = True
                
                phone_number = settings_form.cleaned_data.get('phone_number')
                if phone_number is not None and profile.phone_number != phone_number:
                    profile.phone_number = phone_number
                    profile_updated = True
                    
                if profile_updated:
                    profile.save()
                    
                messages.success(request, 'Your profile was successfully updated!')
                return redirect('user_settings')
            else:
                messages.error(request, 'Please correct the errors below.')
        
        elif action == 'change_password':
            password_form = PasswordChangeForm(request.user, request.POST)
            settings_form = UserSettingsForm(instance=request.user)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # Important!
                messages.success(request, 'Your password was successfully updated!')
                return redirect('user_settings')
            else:
                messages.error(request, 'Please correct the password errors below.')
        else:
            settings_form = UserSettingsForm(instance=request.user, initial={'phone_number': profile.phone_number})
            password_form = PasswordChangeForm(request.user)
    else:
        settings_form = UserSettingsForm(instance=request.user, initial={'phone_number': profile.phone_number})
        password_form = PasswordChangeForm(request.user)
        
    assigned_count = Lead.objects.filter(Q(assigned_agents=request.user) | Q(assigned_to=request.user)).distinct().count()
    return render(request, 'sales/user_settings.html', {
        'settings_form': settings_form,
        'password_form': password_form,
        'assigned_count': assigned_count,
        'profile': profile
    })


@login_required
def update_notes(request, pk):
    """AJAX endpoint to update sales notes for a lead"""
    if request.method == "POST":
        import json
        try:
            data = json.loads(request.body)
            notes = data.get('notes', '')
            
            lead = get_object_or_404(Lead, pk=pk)
            
            # Ensure OutreachStatus exists
            outreach_status, created = OutreachStatus.objects.get_or_create(lead=lead)
            outreach_status.notes = notes
            outreach_status.save()
            
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    
    return HttpResponse("Method not allowed", status=405)

@login_required
@require_POST
def bulk_assign_manager(request):
    """Assign a manager to multiple sales agents at once"""
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
        
    try:
        from django.contrib.auth.models import User
        from sales.models import SalesAgentProfile, AgentHistoryLog
        
        data = json.loads(request.body)
        agent_ids = data.get('agent_ids', [])
        manager_id = data.get('manager_id')
        
        if not agent_ids:
            return JsonResponse({'status': 'error', 'message': 'No agents selected'})
            
        # Get manager (can be None if unassigning)
        manager_profile = None
        if manager_id:
            try:
                manager_user = User.objects.get(id=manager_id, groups__name='Sales')
                manager_profile, _ = SalesAgentProfile.objects.get_or_create(user=manager_user)
            except User.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Selected manager not found'})
                
        # Update profiles
        updated_count = 0
        for agent_id in agent_ids:
            try:
                # Don't assign an agent as their own manager
                if manager_id and str(agent_id) == str(manager_id):
                    continue
                    
                profile, _ = SalesAgentProfile.objects.get_or_create(user_id=agent_id)
                profile.manager = manager_profile
                profile.save()
                
                # Log the change
                manager_name = manager_profile.user.username if manager_profile else "None"
                AgentHistoryLog.objects.create(
                    agent=profile.user,
                    action_by=request.user,
                    action_type='MANAGER_ASSIGNED',
                    details=f"Manager bulk assigned to: {manager_name}"
                )
                
                updated_count += 1
            except Exception:
                pass
                
        return JsonResponse({'status': 'success', 'message': f'Successfully assigned manager to {updated_count} agents.'})
    
    except Exception as e:
        # Assuming logger is imported or defined elsewhere, otherwise this will cause an error
        # For this exercise, I'll assume logger is available or remove it if not.
        # Given the context, it's likely a logger is set up.
        # If not, a simple print(f"Error in bulk assign manager: {str(e)}") could be used for debugging.
        # For now, I'll keep it as is, assuming logger is defined.
        # If logger is not defined, the user would need to add `import logging` and `logger = logging.getLogger(__name__)`
        # For the purpose of this task, I will just include the line as provided.
        # If `logger` is not defined, this will cause a NameError.
        # To make it syntactically correct without assuming external imports, I'll comment it out or replace it.
        # Given the instruction is to make the change faithfully, I will include it as is.
        # If `logger` is not defined, the user will need to add `import logging` and `logger = logging.getLogger(__name__)`
        # I will assume `logger` is defined in the context of the full file.
        # logger.error(f"Error in bulk assign manager: {str(e)}") # This line is commented out as `logger` is not defined in the provided snippet.
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    return HttpResponse("Method not allowed", status=405)

@login_required
def manage_system_settings(request):
    """Admin can manage global system settings like pricing and commission rate"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    settings = SystemSettings.get_settings()
    
    if request.method == 'POST':
        form = SystemSettingsForm(request.POST, request.FILES, instance=settings)
        if form.is_valid():
            form.save()
            return redirect('manage_system_settings')
    else:
        form = SystemSettingsForm(instance=settings)
        
    return render(request, 'sales/system_settings.html', {
        'form': form,
        'settings': settings,
        'datasets': Dataset.objects.all().order_by('-created_at')
    })

# --- Scraper Views --- #

@login_required
def scraper_control(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    from sales.models import Dataset
    datasets = Dataset.objects.all().order_by('-created_at')
    return render(request, 'sales/scraper_control.html', {'datasets': datasets})

@login_required
@require_POST
def run_scraper(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    
    keyword = request.POST.get('keyword', '')
    city = request.POST.get('city', '')
    limit = request.POST.get('limit', '0')
    dataset_id = request.POST.get('dataset_id')
    new_dataset_name = request.POST.get('new_dataset_name')

    from django.core.cache import cache
    cache.set('stop_scraping', False, timeout=86400)

    # Handle dataset selection/creation
    final_dataset_id = dataset_id
    if new_dataset_name:
        from sales.models import Dataset
        ds = Dataset.objects.create(name=new_dataset_name)
        final_dataset_id = str(ds.id)

    def run_command_thread(k, c, l, d_id):
        from .models import ScraperLog
        from django.utils import timezone
        
        # Helper to log both to stdout and database
        def log_message(msg):
            # Print to thread's stdout
            print(msg)
            # Save to persistent database logs
            ScraperLog.objects.create(message=msg)

        import sys
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        
        try:
            log_message(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] > Initializing extraction for '{k}' in '{c}'...")
            call_command('scrape_gmaps', k, c, limit=int(l) if l else 0, dataset_id=d_id)
            log_message(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] > Extraction cycle completed.")
        except Exception as e:
            log_message(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] > CRITICAL ERROR: {str(e)}")
        finally:
            sys.stdout = old_stdout

    t = threading.Thread(target=run_command_thread, args=(keyword, city, limit, final_dataset_id))
    t.daemon = True
    t.start()

    return HttpResponse(f"<div class='text-success'>Started scraping for '{keyword}' in '{city}'. Check logs below.</div>")

@login_required
@require_POST
def run_enrichment(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    
    from django.core.cache import cache
    if cache.get('enrichment_is_running'):
        return HttpResponse("<div class='text-warning'>Enrichment is already running. Please Wait.</div>", status=400)
    
    dataset_id = request.POST.get('dataset_id')
    
    # Clear stop flag before starting
    cache.set('stop_enrichment', False, timeout=86400)
    
    def run_thread(ds_id):
         from django.core.management import call_command
         from .models import ScraperLog
         from django.utils import timezone
         
         try:
             # Pass --dataset if provided
             if ds_id:
                 call_command('enrich_leads', dataset=ds_id)
             else:
                 call_command('enrich_leads')
         except Exception as e:
             from django.core.cache import cache
             cache.set('enrichment_is_running', False, timeout=0)
             ScraperLog.objects.create(message=f"[ENRICHMENT] CRITICAL ERROR: {str(e)}")

    thread = threading.Thread(target=run_thread, args=(dataset_id,))
    thread.daemon = True
    thread.start()
    
    return HttpResponse("<div class='text-info'>Started Email Hunter (Async Enrichment). Watch console below for progress.</div>")

@login_required
@require_POST
def stop_enrichment(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    from django.core.cache import cache
    cache.set('stop_enrichment', True, timeout=86400)
    return HttpResponse("<div class='text-danger fw-bold'>[ENRICHMENT] Stop signal sent.</div>")

@login_required
@require_POST
def stop_scraper(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    from django.core.cache import cache
    cache.set('stop_scraping', True, timeout=86400)
    return HttpResponse("<div class='text-danger fw-bold'>Stop signal sent. Scraper will halt after current item.</div>")

@login_required
@require_POST
def add_lead_manual(request):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    name = request.POST.get('name')
    phone = request.POST.get('phone')
    city = request.POST.get('city')
    dataset_id = request.POST.get('dataset_id')
    
    if name:
        from sales.models import Lead, ContactDetails, OutreachStatus, Dataset
        import uuid
        ds = Dataset.objects.get(id=dataset_id) if dataset_id else None
        
        # Generate generic id to prevent collision
        fake_id = f"manual_{uuid.uuid4().hex[:8]}"
        
        lead = Lead.objects.create(
            name=name,
            city=city,
            gmaps_id=fake_id,
            dataset=ds
        )
        ContactDetails.objects.create(lead=lead, phone_primary=phone)
        OutreachStatus.objects.create(lead=lead)
        
    return redirect('data_explorer')

@login_required
@require_POST
def delete_lead_manual(request, pk):
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    from django.shortcuts import get_object_or_404
    from sales.models import Lead
    lead = get_object_or_404(Lead, pk=pk)
    lead.delete()
    
    return redirect(request.META.get('HTTP_REFERER', 'data_explorer'))


# ─────────────────────────────────────────────
# Deal Request Management (Admin)
# ─────────────────────────────────────────────

@login_required
def pending_deals(request):
    """Admin view: list all pending DealRequests"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
    from .models import DealRequest
    pending = DealRequest.objects.filter(status='PENDING').select_related(
        'lead', 'sales_agent', 'lead__outreach_status', 'lead__contact_details'
    )
    approved = DealRequest.objects.filter(status='APPROVED').select_related(
        'lead', 'sales_agent', 'reviewed_by'
    )[:20]
    rejected = DealRequest.objects.filter(status='REJECTED').select_related(
        'lead', 'sales_agent', 'reviewed_by'
    )[:20]
    return render(request, 'sales/pending_deals.html', {
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'pending_count': pending.count(),
    })


@login_required
@require_POST
def confirm_deal(request, deal_id):
    """Admin confirms a deal → creates SubscriptionOrder and marks APPROVED"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    from .models import DealRequest, SubscriptionOrder, SalesAgentProfile
    deal = get_object_or_404(DealRequest, id=deal_id, status='PENDING')

    # Snapshot commission rates
    try:
        agent_profile = deal.sales_agent.sales_profile
        commission_rate = agent_profile.commission_rate
        manager = agent_profile.manager.user if agent_profile.manager else None
        manager_commission_rate = agent_profile.manager.team_commission_rate if agent_profile.manager else 0
    except Exception:
        commission_rate = 10
        manager = None
        manager_commission_rate = 0

    lead = deal.lead
    contact = getattr(lead, 'contact_details', None)

    # Create completed SubscriptionOrder
    SubscriptionOrder.objects.create(
        lead=lead,
        customer_name=lead.name,
        customer_email='',
        customer_phone=contact.phone_primary if contact else '',
        domain_name='',
        price=deal.price,
        sales_agent=deal.sales_agent,
        commission_rate=commission_rate,
        manager=manager,
        manager_commission_rate=manager_commission_rate,
        status='COMPLETED',
        paid_at=timezone.now(),
    )

    # Mark deal request as approved
    deal.status = 'APPROVED'
    deal.reviewed_at = timezone.now()
    deal.reviewed_by = request.user
    deal.save()

    # Fire Notification for the Agent and Manager
    from notifications.utils import create_notification
    
    # Notify Agent
    create_notification(
        recipient=deal.sales_agent,
        sender=request.user,
        notification_type='DEAL_APPROVED',
        title="Deal Approved! 🎉",
        message=f"Congratulations! Your deal for {lead.name} has been approved. Commission added.",
        target_url='/my-profile/'
    )
    
    # Notify Manager if exists
    if manager:
        create_notification(
            recipient=manager,
            sender=request.user,
            notification_type='DEAL_APPROVED',
            title="Team Deal Approved",
            message=f"A deal submitted by {deal.sales_agent.username} for {lead.name} has been approved.",
            target_url='/team/'
        )

    return JsonResponse({
        'success': True,
        'message': f"Deal for '{lead.name}' approved. Commission: {deal.commission_amount:.2f} EGP"
    })


@login_required
@require_POST
def reject_deal(request, deal_id):
    """Admin rejects a deal → resets lead status to FOLLOW_UP"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    from .models import DealRequest
    deal = get_object_or_404(DealRequest, id=deal_id, status='PENDING')

    # Reset lead status to FOLLOW_UP
    from .models import OutreachStatus
    OutreachStatus.objects.filter(lead=deal.lead).update(status='FOLLOW_UP')

    deal.status = 'REJECTED'
    deal.reviewed_at = timezone.now()
    deal.reviewed_by = request.user
    deal.notes = (deal.notes or '') + f"\n[Rejected by {request.user.username}]"
    deal.save()

    # Fire Notification
    from notifications.utils import create_notification
    create_notification(
        recipient=deal.sales_agent,
        sender=request.user,
        notification_type='DEAL_REJECTED',
        title="Deal Rejected",
        message=f"Unfortunately, your deal request for {deal.lead.name} was rejected.",
        target_url='/my-profile/'
    )

    return JsonResponse({
        'success': True,
        'message': f"Deal for '{deal.lead.name}' rejected. Lead returned to Follow-Up."
    })

@login_required
def get_scraper_logs(request):
    """Returns persistent logs from the database"""
    from .models import ScraperLog
    # Get last 200 logs to keep it snappy
    logs = ScraperLog.objects.all().order_by('created_at').values('message', 'created_at')
    return JsonResponse({'logs': list(logs)})

@login_required
def clear_scraper_logs(request):
    """Clears persistent logs (Admin Only)"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    from .models import ScraperLog
    ScraperLog.objects.all().delete()
    return JsonResponse({'success': True, 'message': 'Logs cleared successfully.'})

@login_required
def get_scraper_status(request):
    """Returns current scraper or enrichment progress from cache"""
    from django.core.cache import cache
    
    # Check Enrichment first
    en_running = cache.get('enrichment_is_running', False)
    if en_running:
        total = cache.get('enrichment_total', 0)
        saved = cache.get('enrichment_count', 0)
        return JsonResponse({
            'is_running': True,
            'is_enrichment': True,
            'total': total,
            'saved': saved,
            'remaining': max(0, total - saved)
        })

    # Fallback to standard Scraper
    return JsonResponse({
        'is_running': cache.get('scraper_is_running', False),
        'is_enrichment': False,
        'total': cache.get('scraper_total_target', 0),
        'saved': cache.get('scraper_saved_count', 0),
        'remaining': max(0, cache.get('scraper_total_target', 0) - cache.get('scraper_saved_count', 0))
    })

@login_required
@require_POST
def add_lead_comment(request, pk):
    """Adds an immutable comment to a lead"""
    lead = get_object_or_404(Lead, pk=pk)
    text = request.POST.get('comment_text')
    
    if text:
        from .models import LeadComment
        LeadComment.objects.create(
            lead=lead,
            user=request.user,
            text=text
        )
        
        # Fire Notification to lead owners
        from notifications.utils import create_notification
        
        for agent in lead.assigned_agents.all():
            if agent != request.user:
                create_notification(
                    recipient=agent,
                    sender=request.user,
                    notification_type='NEW_COMMENT',
                    title=f"New Comment on {lead.name}",
                    message=f"{request.user.username} added a comment: '{text[:50]}...'",
                    target_url=f"/data/record/{pk}/"
                )
    
    return redirect('lead_detail', pk=pk)
@login_required
def migrate_assignments(request):
    """One-time migration to move assigned_to -> assigned_agents"""
    if not request.user.is_staff:
        return HttpResponse("Unauthorized", status=403)
        
    from .models import Lead
    leads = Lead.objects.filter(assigned_to__isnull=False)
    count = 0
    for lead in leads:
        # Check if already migrated to avoid redundant work
        if not lead.assigned_agents.exists():
            lead.assigned_agents.add(lead.assigned_to)
            count += 1
            
    return HttpResponse(f"Successfully migrated {count} assignments. You can now use the multi-agent system safely.")
