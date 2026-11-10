import pandas as pd
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from .models import Dataset, Lead, ContactDetails, OutreachStatus
from io import BytesIO

def is_admin(user):
    return user.is_staff

def safe_int(val, default=0):
    try:
        if pd.isna(val) or val is None or str(val).strip() == '':
            return default
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default

def safe_float(val, default=0.0):
    try:
        if pd.isna(val) or val is None or str(val).strip() == '':
            return default
        return float(str(val).strip())
    except (ValueError, TypeError):
        return default

@login_required
@user_passes_test(is_admin)
def import_data(request):
    if request.method == 'POST':
        dataset_name = request.POST.get('dataset_name')
        file = request.FILES.get('file')
        
        if not dataset_name or not file:
            messages.error(request, "Please provide a dataset name and a file.")
            return redirect('import_data')
            
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file)
            elif file.name.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file)
            else:
                messages.error(request, "File format not supported. Please upload CSV or Excel.")
                return redirect('import_data')
                
            # Store dataframe in session as dict
            # For simplicity with datasets we could just save temp file or save to session
            request.session['import_data'] = df.to_dict('records')
            request.session['import_columns'] = df.columns.tolist()
            request.session['dataset_name'] = dataset_name
            
            return redirect('map_excel_fields')
            
        except Exception as e:
            messages.error(request, f"Error reading file: {str(e)}")
            return redirect('import_data')
            
    return render(request, 'sales/import_data.html')

@login_required
@user_passes_test(is_admin)
def map_excel_fields(request):
    columns = request.session.get('import_columns', [])
    data = request.session.get('import_data', [])
    dataset_name = request.session.get('dataset_name', 'Untitled Dataset')
    
    if not columns or not data:
        messages.warning(request, "No import session found. Please upload a file first.")
        return redirect('import_data')
        
    db_fields = {
        'name': 'Lead Name',
        'city': 'City',
        'address': 'Address',
        'rating': 'Rating (Number)',
        'reviews_count': 'Total Reviews',
        'phone_primary': 'Primary Phone',
        'website_url': 'Website URL',
        'messages': 'Messages (System)',
        'status': 'Status (e.g., NOT_CONTACTED)',
    }
    
    if request.method == 'POST':
        visible_columns = request.POST.getlist('visible_columns')
        mapping = {}
        column_labels = {}
        for db_field, db_label in db_fields.items():
            col = request.POST.get(f"map_{db_field}")
            label = request.POST.get(f"label_{db_field}", db_label)
            if col:
                mapping[db_field] = col
            column_labels[db_field] = label
                
        # Create Dataset
        dataset = Dataset.objects.create(
            name=dataset_name,
            visible_columns=visible_columns,
            column_labels=column_labels
        )
        
        # Process rows
        success_count = 0
        for row in data:
            name_col = mapping.get('name')
            if not name_col or pd.isna(row.get(name_col)) or not row.get(name_col):
                continue
                
            name_val = str(row.get(name_col))
            city_val = str(row.get(mapping.get('city'))) if mapping.get('city') and not pd.isna(row.get(mapping.get('city'))) else "Unknown"
            
            # Create Lead
            lead = Lead.objects.create(
                name=name_val,
                city=city_val[:100],
                dataset=dataset,
                address=str(row.get(mapping.get('address'))) if mapping.get('address') and not pd.isna(row.get(mapping.get('address'))) else "",
                rating=safe_float(row.get(mapping.get('rating')), 0.0),
                reviews_count=safe_int(row.get(mapping.get('reviews_count')), 0),
                website_url=str(row.get(mapping.get('website_url'))) if mapping.get('website_url') and not pd.isna(row.get(mapping.get('website_url'))) else "",
                has_website=bool(mapping.get('website_url') and not pd.isna(row.get(mapping.get('website_url'))))
            )
            
            # Create Contact Details
            ContactDetails.objects.create(
                lead=lead,
                phone_primary=str(row.get(mapping.get('phone_primary'))) if mapping.get('phone_primary') and not pd.isna(row.get(mapping.get('phone_primary'))) else ""
            )
            
            # Create Outreach Status
            status_val = str(row.get(mapping.get('status'))).upper() if mapping.get('status') and not pd.isna(row.get(mapping.get('status'))) else 'NOT_CONTACTED'
            valid_statuses = [choice[0] for choice in OutreachStatus.STATUS_CHOICES]
            if status_val not in valid_statuses:
                status_val = 'NOT_CONTACTED'
                
            OutreachStatus.objects.create(
                lead=lead,
                status=status_val
            )
            success_count += 1
            
        # Clean session
        del request.session['import_data']
        del request.session['import_columns']
        del request.session['dataset_name']
        
        messages.success(request, f"Successfully imported {success_count} records into dataset '{dataset.name}'.")
        return redirect('data_explorer_dataset', dataset_id=dataset.id)
        
    return render(request, 'sales/map_fields.html', {
        'columns': columns,
        'db_fields': db_fields,
        'dataset_name': dataset_name
    })

@login_required
@user_passes_test(is_admin)
def edit_dataset(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id)
    
    db_fields = {
        'name': 'Lead Name',
        'city': 'City',
        'address': 'Address',
        'rating': 'Rating (Number)',
        'reviews_count': 'Total Reviews',
        'phone_primary': 'Primary Phone',
        'website_url': 'Website URL',
        'messages': 'Messages (System)',
        'status': 'Status (e.g., NOT_CONTACTED)',
    }
    
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            dataset.name = name
            
        visible_columns = request.POST.getlist('visible_columns')
        dataset.visible_columns = visible_columns
        
        column_labels = {}
        for db_key in db_fields.keys():
            label = request.POST.get(f"label_{db_key}")
            if label:
                column_labels[db_key] = label
        
        column_labels = column_labels
        
        # Save product settings
        dataset.product_name = request.POST.get('product_name')
        dataset.product_description = request.POST.get('product_description')
        
        price_val = request.POST.get('product_price')
        if price_val and price_val.strip():
            try:
                dataset.product_price = safe_float(price_val)
            except:
                pass
        else:
            dataset.product_price = None
            
        dataset.save()
        
        messages.success(request, f"Dataset '{dataset.name}' updated successfully.")
        return redirect('data_explorer_dataset', dataset_id=dataset.id)
        
    return render(request, 'sales/edit_dataset.html', {
        'dataset': dataset,
        'db_fields': db_fields,
    })

@login_required
@user_passes_test(is_admin)
def delete_dataset(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id)
    if request.method == 'POST':
        name = dataset.name
        dataset.delete()
        messages.success(request, f"Dataset '{name}' has been deleted along with all related records.")
        return redirect('manage_system_settings')
    return redirect('manage_system_settings')

@login_required
@user_passes_test(is_admin)
def bulk_delete_datasets(request):
    if request.method == 'POST':
        dataset_ids = request.POST.getlist('dataset_ids')
        if not dataset_ids:
            messages.warning(request, "No datasets selected for deletion.")
            return redirect('manage_system_settings')
            
        count = Dataset.objects.filter(id__in=dataset_ids).count()
        Dataset.objects.filter(id__in=dataset_ids).delete()
        
        messages.success(request, f"Successfully deleted {count} datasets and all their records.")
    return redirect('manage_system_settings')

