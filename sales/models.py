from django.db import models
import uuid
from django.utils import timezone
from django.contrib.auth.models import User

class Dataset(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    visible_columns = models.JSONField(default=list, help_text="List of columns to display in Data Explorer")
    column_labels = models.JSONField(default=dict, help_text="Custom labels for columns", blank=True)
    
    # Dataset-specific product settings
    product_name = models.CharField(max_length=255, null=True, blank=True, help_text="Override system product name")
    product_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Override system product price")
    product_description = models.TextField(null=True, blank=True, help_text="Override system product description")

    def __str__(self):
        return self.name

class Lead(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, null=True, blank=True, related_name='leads')
    SIZE_CHOICES = [
        ('STARTUP', 'Startup'),
        ('MEDIUM', 'Medium'),
        ('LARGE', 'Large'),
        ('UNKNOWN', 'Unknown'),
    ]

    name = models.CharField(max_length=255)
    gmaps_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    city = models.CharField(max_length=100, db_index=True)
    address = models.TextField(null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    has_website = models.BooleanField(default=False)
    website_url = models.URLField(max_length=500, null=True, blank=True)
    
    rating = models.FloatField(default=0.0)
    reviews_count = models.IntegerField(default=0)
    photos_count = models.IntegerField(default=0)
    business_size = models.CharField(max_length=20, choices=SIZE_CHOICES, default='UNKNOWN')
    
    has_branches = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_scraped_at = models.DateTimeField(auto_now=True)
    
    
    # Sales Team Assignment
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_leads', help_text="[Legacy] Single agent responsible for this lead")
    assigned_agents = models.ManyToManyField(User, related_name='leads_assigned', blank=True, help_text="Agents working on this lead")

    def __str__(self):
        return self.name


class ContactDetails(models.Model):
    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name='contact_details')
    phone_primary = models.CharField(max_length=50, null=True, blank=True)
    phone_whatsapp = models.CharField(max_length=50, null=True, blank=True)
    
    email_list = models.JSONField(default=list, blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    
    # NEW: WhatsApp Content Fields
    message_body = models.TextField(null=True, blank=True, help_text="Custom message content for this contact")
    second_message = models.TextField(null=True, blank=True, help_text="Second follow-up message")
    last_message_received = models.TextField(null=True, blank=True, help_text="The last reply received from the customer")
    auto_reply_sent = models.BooleanField(default=False, help_text="Has the auto-reply been triggered?")

    def __str__(self):
        return f"Contacts for {self.lead.name}"


class OutreachStatus(models.Model):
    STATUS_CHOICES = [
        ('NOT_CONTACTED', 'Not Contacted'),
        ('SYNCED', 'Synced (In Phones)'),
        ('SENT', 'Message Sent'),
        ('DELIVERED', 'Message Delivered'),
        ('READ', 'Message Read'),
        ('REPLIED', 'Customer Replied'),
        ('FOLLOW_UP', 'Following Up'),
        ('DEAL', 'Deal Closed'),
        ('NO_DEAL', 'No Deal'),
    ]

    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name='outreach_status')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NOT_CONTACTED', db_index=True)
    last_contact_date = models.DateTimeField(null=True, blank=True)
    follow_up_date = models.DateTimeField(null=True, blank=True, help_text="Scheduled follow-up date and time")
    follow_up_notes = models.TextField(null=True, blank=True, help_text="Notes specifically for this follow-up")
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.lead.name} - {self.status}"


class SystemSettings(models.Model):
    """System-wide settings for product pricing and global configuration (Singleton)"""
    # Singleton Pattern - only one record allowed
    
    # Branding
    site_name = models.CharField(max_length=200, default="RMS Admin")
    logo = models.ImageField(upload_to='site_logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=7, default="#0d6efd", help_text="Hex primary color (e.g. #0d6efd)")
    secondary_color = models.CharField(max_length=7, default="#6c757d", help_text="Hex secondary color")
    text_color = models.CharField(max_length=7, default="#1e293b", help_text="Hex text color (e.g. #1e293b)")
    
    # Dark Mode Branding
    dark_primary_color = models.CharField(max_length=7, default="#3b82f6", help_text="Dark mode primary color")
    dark_secondary_color = models.CharField(max_length=7, default="#475569", help_text="Dark mode secondary color")
    dark_text_color = models.CharField(max_length=7, default="#f1f5f9", help_text="Dark mode text color")
    
    # Product Info
    product_name = models.CharField(max_length=200, default="Lead Management System")
    product_description = models.TextField(default="Complete lead management solution with custom website and domain", blank=True)
    
    # Dynamic Price - Admin-Controlled
    product_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=10000.00, 
        help_text="Current product price in EGP (Admin can update)"
    )
    currency = models.CharField(max_length=3, default='EGP')
    
    # Commission Settings
    default_commission_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00, 
        help_text="Default commission percentage for sales agents"
    )
    
    # Message Templates
    first_message_template = models.TextField(
        default="",
        blank=True,
        help_text="Template for the first message. Placeholders: {name}, {rating}, {reviews_count}, {city}, {product_price}"
    )
    
    second_message_template = models.TextField(
        default="",
        blank=True,
        help_text="Template for the second message. Placeholders: {name}, {product_price}"
    )
    
    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='settings_updates'
    )
    
    class Meta:
        verbose_name = 'System Settings'
        verbose_name_plural = 'System Settings'
    
    def save(self, *args, **kwargs):
        # Singleton Pattern: Ensure ID is always 1
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def get_settings(cls):
        """Get or create the single settings instance"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings
    
    def __str__(self):
        return f"{self.product_name} - {self.product_price} {self.currency}"

class SalesAgentProfile(models.Model):
    """Profile model for tracking sales agent activity and performance"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='sales_profile')
    last_active_at = models.DateTimeField(null=True, blank=True)
    total_work_hours_today = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_work_hours_week = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_work_hours_month = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    joined_date = models.DateTimeField(auto_now_add=True)
    is_active_session = models.BooleanField(default=False)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    
    # Secure Identifier for URLs
    agent_uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # Commission Settings
    commission_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00,
        help_text="Commission percentage for this agent (overrides default if set)"
    )
    
    # Manager & Team Settings
    manager = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='subordinates',
        help_text="The manager of this sales agent"
    )
    team_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=2.00,
        help_text="Percentage this agent earns from their subordinates' sales"
    )
    
    @property
    def total_sales(self):
        """Number of completed sales"""
        return self.user.sales_orders.filter(status='COMPLETED').count()
    
    @property
    def total_revenue(self):
        """Total revenue generated from sales"""
        from django.db.models import Sum
        result = self.user.sales_orders.filter(status='COMPLETED').aggregate(Sum('price'))
        return result['price__sum'] or 0
    
    @property
    def total_commission(self):
        """Total commission earned directly"""
        orders = self.user.sales_orders.filter(status='COMPLETED')
        return sum(order.commission_amount for order in orders)
        
    @property
    def total_team_commission(self):
        """Total commission earned from subordinates' sales"""
        orders = self.user.manager_sales_orders.filter(status='COMPLETED')
        return sum(order.manager_commission_amount for order in orders)
        
    @property
    def total_earned(self):
        """Total commission (direct + team)"""
        return self.total_commission + self.total_team_commission
        
    @property
    def total_paid(self):
        """Total amount paid to this agent manually by admin"""
        from django.db.models import Sum
        result = self.user.payouts.aggregate(Sum('amount'))
        return result['amount__sum'] or 0
        
    @property
    def current_balance(self):
        """Remaining balance (earned - paid)"""
        return self.total_earned - self.total_paid
    
    class Meta:
        verbose_name = 'Sales Agent Profile'
        verbose_name_plural = 'Sales Agent Profiles'
    
    def __str__(self):
        return f"{self.user.username} Profile"
    
    @property
    def is_team_lead(self):
        """Returns True if this agent has subordinates"""
        return self.subordinates.exists()
    
    @property
    def status(self):
        """Returns online status based on last activity"""
        if not self.last_active_at:
            return 'offline'
        
        from django.utils import timezone
        time_diff = timezone.now() - self.last_active_at
        
        if time_diff.total_seconds() < 300:  # 5 minutes
            return 'online'
        elif time_diff.total_seconds() < 1800:  # 30 minutes
            return 'away'
        else:
            return 'offline'
    
    @property
    def status_display(self):
        """Returns user-friendly status display"""
        status = self.status
        if status == 'online':
            return '🟢 Online'
        elif status == 'away':
            return '🟡 Away'
        else:
            return '🔴 Offline'




class SubscriptionOrder(models.Model):
    """Customer subscription orders with Paymob integration"""
    
    # Customer Information
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    domain_name = models.CharField(max_length=255, help_text="Customer's requested domain name")
    
    # Price Snapshot (at time of purchase)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='EGP')
    
    # Sales Agent Tracking
    sales_agent = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='sales_orders',
        help_text="Agent credited for this sale"
    )
    
    # Commission snapshot (at time of sale)
    commission_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00,
        help_text="Commission rate at time of sale"
    )
    
    # Manager tracking snapshot (at time of sale)
    manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_sales_orders',
        help_text="Manager credited for team commission on this sale"
    )
    manager_commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        help_text="Manager's commission rate at time of sale"
    )
    
    # Paymob Integration Fields
    paymob_order_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    paymob_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_token = models.TextField(blank=True, null=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    
    # Transaction Details
    paid_at = models.DateTimeField(blank=True, null=True)
    hmac_verified = models.BooleanField(default=False)
    
    # Order Status
    STATUS_CHOICES = [
        ('PENDING', 'Pending Payment'),
        ('PROCESSING', 'Processing Payment'),
        ('COMPLETED', 'Payment Completed'),
        ('FAILED', 'Payment Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Subscription Order'
        verbose_name_plural = 'Subscription Orders'
    
    @property
    def commission_amount(self):
        """Calculate commission amount"""
        return (self.price * self.commission_rate) / 100
        
    @property
    def manager_commission_amount(self):
        """Calculate manager's team commission amount"""
        if self.manager and self.manager_commission_rate > 0:
            return (self.price * self.manager_commission_rate) / 100
        return 0
    
    @property
    def net_revenue(self):
        """Net revenue after all commissions"""
        return self.price - self.commission_amount - self.manager_commission_amount
    
    def __str__(self):
        return f"Order #{self.id} - {self.customer_name} - {self.status}"


class AgentPayout(models.Model):
    """Tracks manual commission payments made from Admin to Sales Agents"""
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True, help_text="Transaction reference or admin notes")
    
    class Meta:
        ordering = ['-payment_date']
        verbose_name = 'Agent Payout'
        verbose_name_plural = 'Agent Payouts'
        
    def __str__(self):
        return f"Payout of {self.amount} to {self.agent.username} on {self.payment_date.strftime('%Y-%m-%d')}"

class AgentHistoryLog(models.Model):
    """Tracks changes and actions performed on a sales agent profile"""
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='history_logs', help_text="The sales agent who was modified")
    action_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='performed_agent_actions', help_text="The user (admin/manager) who made the change")
    
    ACTION_CHOICES = [
        ('CONFIG_UPDATE', 'Configuration Updated'),
        ('STATUS_CHANGE', 'Status Changed'),
        ('PASSWORD_RESET', 'Password Reset'),
        ('MANAGER_ASSIGNED', 'Manager Assigned'),
        ('LEAD_TRANSFER', 'Leads Transferred'),
        ('PAYOUT', 'Payout Recorded'),
        ('OTHER', 'Other Action')
    ]
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES)
    
    details = models.TextField(help_text="Description of what was changed")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Agent History Log'
        verbose_name_plural = 'Agent History Logs'
        
    def __str__(self):
        return f"{self.agent.username} - {self.get_action_type_display()} on {self.created_at.strftime('%Y-%m-%d %H:%M')}"

class IdempotencyKey(models.Model):
    key = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return str(self.key)


class DealRequest(models.Model):
    """
    Represents a deal submitted by a Sales Agent awaiting Admin confirmation.
    Created automatically when a lead's status is set to DEAL.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending Admin Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    lead = models.OneToOneField(
        Lead,
        on_delete=models.CASCADE,
        related_name='deal_request',
        help_text="The lead this deal is associated with"
    )
    sales_agent = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='deal_requests',
        help_text="The sales agent who closed the deal"
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Agreed deal price with the customer (EGP)"
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes about the deal"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_deals',
        help_text="Admin who approved or rejected the deal"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Deal Request'
        verbose_name_plural = 'Deal Requests'

    @property
    def commission_amount(self):
        """Calculate agent's commission based on their profile rate"""
        try:
            rate = self.sales_agent.sales_profile.commission_rate
            return (self.price * rate) / 100
        except Exception:
            return 0

    def __str__(self):
        return f"Deal #{self.id} — {self.lead.name} by {self.sales_agent.username} [{self.status}]"

class LeadComment(models.Model):
    """
    Immutable comments for a lead. Records author and timestamp.
    """
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lead_comments')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Lead Comment'
        verbose_name_plural = 'Lead Comments'

    def __str__(self):
        return f"Comment by {self.user.username} on {self.lead.name} at {self.created_at}"

class ScraperLog(models.Model):
    """
    Persistent logs for the scraper engine.
    """
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Scraper Log'
        verbose_name_plural = 'Scraper Logs'

    def __str__(self):
        return f"[{self.created_at}] {self.message[:50]}"
