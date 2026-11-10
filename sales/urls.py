from django.urls import path, re_path
from django.views.generic import RedirectView
from . import views, sales_views, sales_dashboard_views, payment_views, import_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('sales/successful-orders/', sales_dashboard_views.successful_sales_dashboard, name='sales_dashboard'),
    path('import/', import_views.import_data, name='import_data'),
    path('import/map/', import_views.map_excel_fields, name='map_excel_fields'),
    path('dataset/<int:dataset_id>/edit/', import_views.edit_dataset, name='edit_dataset'),
    path('dataset/<int:dataset_id>/delete/', import_views.delete_dataset, name='delete_dataset'),
    path('dataset/bulk-delete/', import_views.bulk_delete_datasets, name='bulk_delete_datasets'),
    path('dataset/<int:dataset_id>/import/', views.import_leads_excel, name='import_leads_excel'),
    path('clear-data/', views.clear_data, name='clear_data'),
    path('data/', views.data_explorer, name='data_explorer'),
    path('data/<int:dataset_id>/', views.data_explorer, name='data_explorer_dataset'),
    path('data/record/<int:pk>/', views.lead_detail, name='lead_detail'),
    path('data/add-manual/', views.add_lead_manual, name='add_lead_manual'),
    path('data/<int:pk>/delete/', views.delete_lead_manual, name='delete_lead_manual'),
    path('scraper/control/', views.scraper_control, name='scraper_control'),
    path('scraper/run/', views.run_scraper, name='run_scraper'),
    path('scraper/run-enrichment/', views.run_enrichment, name='enrichment_start'),
    path('scraper/stop-enrichment/', views.stop_enrichment, name='stop_enrichment'),
    path('scraper/stop/', views.stop_scraper, name='stop_scraper'),
    path('scraper/status/', views.get_scraper_status, name='get_scraper_status'),
    path('scraper/logs/fetch/', views.get_scraper_logs, name='get_scraper_logs'),
    path('scraper/logs/clear/', views.clear_scraper_logs, name='clear_scraper_logs'),
    path('migrate-assignments/', views.migrate_assignments, name='migrate_assignments'),
    path('export/', views.export_csv, name='export_csv'),
    path('export-vcf/', views.export_vcf, name='export_vcf'),
    path('generate-messages/', views.generate_intro_messages, name='generate_intro_messages'),
    path('update-status/<int:pk>/', views.update_status, name='update_status'),
    path('update-notes/<int:pk>/', views.update_notes, name='update_notes'),
    path('update-message/<int:pk>/', views.update_message, name='update_message'),
    path('lead/<int:pk>/comment/', views.add_lead_comment, name='add_lead_comment'),
    path('team/', views.manage_team, name='manage_team'),
    path('team/add/', views.add_sales_agent, name='add_sales_agent'),
    path('team/add-admin/', views.add_admin, name='add_admin'),
    path('team/bulk-assign-manager/', views.bulk_assign_manager, name='bulk_assign_manager'),
    # Use sales_views.sales_agent_profile for agent details
    path('agent/<int:agent_id>/', sales_views.sales_agent_profile, name='sales_agent_profile'),
    path('agent/<int:agent_id>/config/', sales_views.update_agent_config, name='update_agent_config'),
    path('agent/<int:pk>/reset-password/', views.admin_reset_password, name='admin_reset_password'),
    path('team/<int:pk>/toggle-status/', views.toggle_agent_status, name='toggle_agent_status'),
    path('record-payout/', views.record_payout, name='record_payout'),
    path('profile/settings/', views.user_settings, name='user_settings'),
    path('data/bulk-assign/', views.bulk_assign_leads, name='bulk_assign_leads'),
    
    # Sales Agent Self-Service
    path('my-profile/', sales_views.my_profile, name='my_profile'),
    path('my-commissions/', sales_views.my_commissions, name='my_commissions'),
    
    # Sales Agent Profile & Management (Admin Only)
    # Sales Agent Profile & Management (Consolidated)
    path('team/<int:agent_id>/profile/', sales_views.sales_agent_profile, name='sales_agent_profile_alias'), # Keep for backward compatibility if needed
    path('team/<int:agent_id>/transfer-leads/', sales_views.transfer_leads, name='transfer_leads'),
    path('team/<int:agent_id>/remove-leads/', sales_views.remove_leads, name='remove_leads'),
    path('team/<int:agent_id>/bulk-transfer/', sales_views.bulk_transfer_leads, name='bulk_transfer_leads'),
    path('team/<int:agent_id>/stats/', sales_views.agent_performance_stats, name='agent_performance_stats'),
    path('team/<int:agent_id>/history/', sales_views.agent_history_full, name='agent_history_full'),
    
    # System Settings (Admin Only)
    path('settings/system/', views.manage_system_settings, name='manage_system_settings'),

    # Deal Management (Admin Only)
    path('deals/pending/', views.pending_deals, name='pending_deals'),
    path('deals/<int:deal_id>/confirm/', views.confirm_deal, name='confirm_deal'),
    path('deals/<int:deal_id>/reject/', views.reject_deal, name='reject_deal'),

    # ==========================
    # 💳 Payment & Checkout URLs
    # ==========================    # Checkout & Payments
    path('checkout/<int:lead_id>/', payment_views.checkout_page, name='checkout_page'),
    path('pay/<uuid:agent_uuid>/', payment_views.public_checkout, name='public_checkout'),
    path('payment/initiate/', payment_views.initiate_payment, name='initiate_payment'),
    path('payment/callback/', payment_views.payment_callback, name='payment_callback'),
    path('payment/success/<int:order_id>/', payment_views.payment_success, name='payment_success'),
    path('payment/failure/<int:order_id>/', payment_views.payment_failure, name='payment_failure'),

    # Redirects for legacy notification URLs
    path('sales/data-explorer/', RedirectView.as_view(url='/data/', permanent=True)),
    path('sales/pending-deals/', RedirectView.as_view(url='/deals/pending/', permanent=True)),
    path('sales/my-profile/', RedirectView.as_view(url='/my-profile/', permanent=True)),
    path('sales/team/', RedirectView.as_view(url='/team/', permanent=True)),
    re_path(r'^sales/details/(?P<pk>\d+)/$', RedirectView.as_view(url='/data/record/%(pk)s/', permanent=True)),
    re_path(r'^sales/agent/(?P<agent_id>\d+)/$', RedirectView.as_view(url='/agent/%(agent_id)s/', permanent=True)),
]
