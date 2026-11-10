from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from sales.models import Lead

class Command(BaseCommand):
    help = 'Setup user roles and groups (Admins, Sales)'

    def handle(self, *args, **options):
        # Create Sales Group
        sales_group, created = Group.objects.get_or_create(name='Sales')
        if created:
            self.stdout.write(self.style.SUCCESS("Created 'Sales' group."))
        else:
            self.stdout.write("Sales group already exists.")

        # Create Admins Group
        admin_group, created = Group.objects.get_or_create(name='Admins')
        if created:
            self.stdout.write(self.style.SUCCESS("Created 'Admins' group."))

        # Assign permissions (Optional - for now we handle logic in views)
        # But good practice to give Sales access to view/change leads if using Django Admin
        content_type = ContentType.objects.get_for_model(Lead)
        permission = Permission.objects.filter(content_type=content_type, codename__in=['view_lead', 'change_lead'])
        sales_group.permissions.set(permission)
        
        self.stdout.write(self.style.SUCCESS("Roles setup complete."))
