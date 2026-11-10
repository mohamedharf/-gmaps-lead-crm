from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import (
    Lead, 
    ContactDetails, 
    OutreachStatus, 
    SalesAgentProfile, 
    SubscriptionOrder, 
    SystemSettings
)

# Inline models
class ContactDetailsInline(admin.StackedInline):
    model = ContactDetails
    can_delete = False
    verbose_name_plural = 'Contact Details'

class OutreachStatusInline(admin.StackedInline):
    model = OutreachStatus
    can_delete = False
    verbose_name_plural = 'Outreach Status'

class SalesAgentProfileInline(admin.StackedInline):
    model = SalesAgentProfile
    can_delete = False
    verbose_name_plural = 'Sales Agent Profile'

# User Admin Extension
class UserAdmin(BaseUserAdmin):
    inlines = (SalesAgentProfileInline,)

# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# Lead Admin
@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'rating', 'reviews_count', 'business_size', 'created_at')
    list_filter = ('city', 'business_size', 'has_website', 'has_branches')
    search_fields = ('name', 'city', 'address')
    inlines = [ContactDetailsInline, OutreachStatusInline]

# System Settings Admin
@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    """Admin interface for system-wide settings"""
    
    list_display = ['product_name', 'product_price', 'currency', 'default_commission_rate', 'updated_at']
    
    fieldsets = (
        ('Product Information', {
            'fields': ('product_name', 'product_description')
        }),
        ('Pricing', {
            'fields': ('product_price', 'currency'),
            'description': 'Update product price here. Changes will reflect immediately on checkout pages.'
        }),
        ('Commission Settings', {
            'fields': ('default_commission_rate',)
        }),
        ('Metadata', {
            'fields': ('updated_at', 'updated_by'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['updated_at', 'updated_by']
    
    def has_add_permission(self, request):
        # Prevent creating multiple records (Singleton)
        return not SystemSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion
        return False
    
    def save_model(self, request, obj, form, change):
        # Track who updated
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

# Subscription Order Admin
@admin.register(SubscriptionOrder)
class SubscriptionOrderAdmin(admin.ModelAdmin):
    """Admin interface for subscription orders"""
    
    list_display = [
        'id',
        'customer_name',
        'customer_email',
        'price',
        'sales_agent',
        'status',
        'paid_at',
        'created_at'
    ]
    
    list_filter = [
        'status',
        'sales_agent',
        'paid_at',
        'created_at',
        'hmac_verified'
    ]
    
    search_fields = [
        'customer_name',
        'customer_email',
        'customer_phone',
        'domain_name',
        'paymob_order_id',
        'paymob_transaction_id'
    ]
    
    readonly_fields = [
        'paymob_order_id',
        'paymob_transaction_id',
        'payment_token',
        'payment_method',
        'hmac_verified',
        'commission_amount_display',
        'net_revenue_display',
        'created_at',
        'updated_at'
    ]
    
    fieldsets = (
        ('Customer Information', {
            'fields': (
                'lead',
                'customer_name',
                'customer_email',
                'customer_phone',
                'domain_name'
            )
        }),
        ('Order Details', {
            'fields': (
                'price',
                'currency',
                'status'
            )
        }),
        ('Sales Agent & Commission', {
            'fields': (
                'sales_agent',
                'commission_rate',
                'commission_amount_display',
                'net_revenue_display'
            )
        }),
        ('Payment Details', {
            'fields': (
                'paymob_order_id',
                'paymob_transaction_id',
                'payment_token',
                'payment_method',
                'paid_at',
                'hmac_verified'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': (
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )
    
    def commission_amount_display(self, obj):
        return f"{obj.commission_amount:.2f} {obj.currency}"
    commission_amount_display.short_description = 'Commission Amount'
    
    def net_revenue_display(self, obj):
        return f"{obj.net_revenue:.2f} {obj.currency}"
    net_revenue_display.short_description = 'Net Revenue'

