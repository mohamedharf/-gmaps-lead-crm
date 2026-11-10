from datetime import timedelta
import random

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from notifications.models import Notification
from sales.models import (
    AgentHistoryLog,
    AgentPayout,
    ContactDetails,
    Dataset,
    DealRequest,
    Lead,
    LeadComment,
    OutreachStatus,
    SalesAgentProfile,
    SubscriptionOrder,
    SystemSettings,
)


class Command(BaseCommand):
    help = 'Seeds the database with realistic demo data for development and screenshots.'

    def handle(self, *args, **options):
        self.stdout.write('--- DEMO SEEDER STARTING ---')

        # 1. SystemSettings
        sys_settings = SystemSettings.get_settings()
        sys_settings.site_name = "GMaps Lead CRM"
        sys_settings.product_name = "SaaS Growth Suite"
        sys_settings.product_description = "Complete lead management solution with custom website and domain"
        sys_settings.product_price = 15000.00
        sys_settings.primary_color = "#2563eb"
        sys_settings.dark_primary_color = "#3b82f6"
        sys_settings.save()

        # 2. Roles & Groups
        sales_group, _ = Group.objects.get_or_create(name='Sales')
        Group.objects.get_or_create(name='Admins')

        # 3. Users and SalesAgentProfiles
        admin_user, created = User.objects.get_or_create(
            username="demo_admin",
            defaults={"email": "admin@example.com", "first_name": "Alex", "last_name": "Morgan"},
        )
        admin_user.set_password('demo1234!')
        admin_user.is_superuser = True
        admin_user.is_staff = True
        admin_user.save()

        manager_user, _ = User.objects.get_or_create(
            username="demo_manager",
            defaults={"email": "manager@example.com", "first_name": "Sarah", "last_name": "Connor"},
        )
        manager_user.set_password('demo1234!')
        manager_user.is_staff = False
        manager_user.save()
        manager_user.groups.add(sales_group)

        agent_user1, _ = User.objects.get_or_create(
            username="demo_agent_1",
            defaults={"email": "agent1@example.com", "first_name": "Omar", "last_name": "Hassan"},
        )
        agent_user1.set_password('demo1234!')
        agent_user1.save()
        agent_user1.groups.add(sales_group)

        agent_user2, _ = User.objects.get_or_create(
            username="demo_agent_2",
            defaults={"email": "agent2@example.com", "first_name": "Nour", "last_name": "Adel"},
        )
        agent_user2.set_password('demo1234!')
        agent_user2.save()
        agent_user2.groups.add(sales_group)

        # Profiles
        admin_profile, _ = SalesAgentProfile.objects.get_or_create(user=admin_user)
        admin_profile.commission_rate = 15.00
        admin_profile.save()

        manager_profile, _ = SalesAgentProfile.objects.get_or_create(user=manager_user)
        manager_profile.commission_rate = 12.00
        manager_profile.team_commission_rate = 3.00
        manager_profile.last_active_at = timezone.now()
        manager_profile.save()

        agent1_profile, _ = SalesAgentProfile.objects.get_or_create(user=agent_user1)
        agent1_profile.manager = manager_profile
        agent1_profile.commission_rate = 10.00
        agent1_profile.total_work_hours_today = 6.5
        agent1_profile.total_work_hours_week = 32.0
        agent1_profile.total_work_hours_month = 120.0
        agent1_profile.last_active_at = timezone.now()
        agent1_profile.save()

        agent2_profile, _ = SalesAgentProfile.objects.get_or_create(user=agent_user2)
        agent2_profile.manager = manager_profile
        agent2_profile.commission_rate = 10.00
        agent2_profile.total_work_hours_today = 4.0
        agent2_profile.total_work_hours_week = 20.0
        agent2_profile.total_work_hours_month = 80.0
        agent2_profile.last_active_at = timezone.now() - timedelta(minutes=15)
        agent2_profile.save()

        # 4. Datasets
        dataset1, _ = Dataset.objects.get_or_create(name="Restaurants in Cairo (Premium)")
        dataset1.product_name = "SaaS Growth Suite + Setup"
        dataset1.product_price = 18000.00
        dataset1.visible_columns = ["city", "rating", "phone", "website", "messages", "status", "assigned_to"]
        dataset1.save()

        dataset2, _ = Dataset.objects.get_or_create(name="Cafes in Alexandria")
        dataset2.visible_columns = ["city", "rating", "phone", "website", "messages", "status", "assigned_to"]
        dataset2.save()

        datasets = [dataset1, dataset2]
        agents = [agent_user1, agent_user2]

        # 5. Leads, ContactDetails, OutreachStatus
        sample_leads = [
            ("Nile Breeze Bistro", "Cairo", 4.8, 1240, True, "https://nilebreeze.example.com", "LARGE", "DEAL"),
            ("Alexandria Roast House", "Alexandria", 4.6, 540, False, None, "MEDIUM", "FOLLOW_UP"),
            ("Pyramids Grill & Lounge", "Giza", 4.7, 890, True, "https://pyramidsgrill.example.com", "LARGE", "REPLIED"),
            ("Delta Specialty Coffee", "Mansoura", 4.5, 310, False, None, "STARTUP", "SENT"),
            ("Zamalek Artisan Bakery", "Cairo", 4.9, 2150, False, None, "MEDIUM", "NOT_CONTACTED"),
            ("Mediterranean Catch", "Alexandria", 4.4, 620, True, "https://medcatch.example.com", "MEDIUM", "FOLLOW_UP"),
        ]

        leads_created = []
        for idx, (name, city, rating, reviews, has_site, site_url, size, status_val) in enumerate(sample_leads):
            assigned_agent = agents[idx % len(agents)] if idx < 5 else None
            lead, created = Lead.objects.get_or_create(
                gmaps_id=f"gmap_demo_id_{idx}",
                defaults={
                    'name': name,
                    'dataset': datasets[idx % len(datasets)],
                    'city': city,
                    'country': 'Egypt',
                    'address': f"10{idx} Corniche El Nil, {city}",
                    'latitude': 30.0444 + (idx * 0.01),
                    'longitude': 31.2357 + (idx * 0.01),
                    'has_website': has_site,
                    'website_url': site_url,
                    'rating': rating,
                    'reviews_count': reviews,
                    'photos_count': 45 + (idx * 30),
                    'business_size': size,
                    'has_branches': size == 'LARGE',
                    'assigned_to': assigned_agent,
                },
            )
            if assigned_agent:
                lead.assigned_agents.add(assigned_agent)
            leads_created.append(lead)

            if created:
                ContactDetails.objects.create(
                    lead=lead,
                    phone_primary=f"+2010{1000000 + idx * 12345}",
                    phone_whatsapp=f"+2010{1000000 + idx * 12345}",
                    email_list=[f"contact@{name.lower().replace(' ', '')}.example.com"] if has_site else [],
                    contact_person=f"Manager {idx + 1}",
                    message_body=f"Hello {name}, we noticed your {rating}★ rating in {city}!",
                    second_message=f"Following up on our SaaS Growth Suite offer for {name}.",
                )
                OutreachStatus.objects.create(
                    lead=lead,
                    status=status_val,
                    last_contact_date=timezone.now() - timedelta(days=idx) if status_val != 'NOT_CONTACTED' else None,
                    follow_up_date=timezone.now() + timedelta(days=2) if status_val == 'FOLLOW_UP' else None,
                    notes=f"Initial qualification completed for {name}.",
                )

        # 6. SubscriptionOrders
        for i in range(6):
            lead = leads_created[i % len(leads_created)]
            agent = lead.assigned_to or agent_user1
            agent_prof = agent.sales_profile
            status = 'COMPLETED' if i < 4 else ('PENDING' if i == 4 else 'FAILED')

            SubscriptionOrder.objects.get_or_create(
                paymob_order_id=f"pm_demo_order_{i}",
                defaults={
                    'lead': lead,
                    'customer_name': lead.name,
                    'customer_email': f"billing{i}@example.com",
                    'customer_phone': f"0101234567{i}",
                    'domain_name': f"business-{i}.example.com",
                    'price': lead.dataset.product_price if lead.dataset and lead.dataset.product_price else sys_settings.product_price,
                    'currency': 'EGP',
                    'sales_agent': agent,
                    'commission_rate': agent_prof.commission_rate,
                    'manager': agent_prof.manager.user if agent_prof.manager else None,
                    'manager_commission_rate': agent_prof.manager.team_commission_rate if agent_prof.manager else 0.00,
                    'status': status,
                    'paid_at': timezone.now() - timedelta(days=i) if status == 'COMPLETED' else None,
                    'hmac_verified': status == 'COMPLETED',
                    'payment_method': 'Card' if status == 'COMPLETED' else None,
                },
            )

        # 7. Sample Pending Deal, Comment, Payout, History, Notification
        if leads_created:
            target_lead = leads_created[1]
            DealRequest.objects.get_or_create(
                lead=target_lead,
                defaults={
                    'sales_agent': agent_user2,
                    'price': 15000.00,
                    'notes': 'Client approved annual package and signed onboarding form.',
                    'status': 'PENDING',
                },
            )
            LeadComment.objects.get_or_create(
                lead=target_lead,
                user=agent_user2,
                text="Spoke with the operations manager; ready for final contract confirmation.",
            )
            Notification.objects.get_or_create(
                recipient=admin_user,
                sender=agent_user2,
                type='DEAL_REQUEST_NEW',
                title='New Deal Request',
                message=f'{agent_user2.username} submitted a deal for {target_lead.name}.',
                target_url='/deals/pending/',
            )

        for agent in agents:
            if not AgentPayout.objects.filter(agent=agent).exists():
                AgentPayout.objects.create(
                    agent=agent,
                    amount=1000.00,
                    notes='Demo monthly commission payout',
                )
            if not AgentHistoryLog.objects.filter(agent=agent).exists():
                AgentHistoryLog.objects.create(
                    agent=agent,
                    action_by=admin_user,
                    action_type='CONFIG_UPDATE',
                    details='Configured initial demo commission rates',
                )

        self.stdout.write(self.style.SUCCESS(
            'Successfully seeded demo database! '
            'Demo login -> admin: demo_admin / demo1234! | agent: demo_agent_1 / demo1234!'
        ))
