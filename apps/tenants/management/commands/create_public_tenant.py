"""
Management command: creates the public tenant and maps localhost to it.
Safe to run multiple times (idempotent).

Usage:
    python manage.py create_public_tenant
"""
from django.core.management.base import BaseCommand
from apps.tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = "Creates the public tenant and maps localhost/127.0.0.1 to it."

    def handle(self, *args, **options):
        tenant, created = Tenant.objects.get_or_create(
            schema_name="public",
            defaults={
                "name": "NetSuite-ISP Platform",
                "contact_email": "platform@netsuite.io",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("✓ Public tenant created."))
        else:
            self.stdout.write("✓ Public tenant already exists.")

        for hostname in ["localhost", "127.0.0.1"]:
            domain, created = Domain.objects.get_or_create(
                domain=hostname,
                defaults={
                    "tenant": tenant,
                    "is_primary": hostname == "localhost",
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✓ Domain '{hostname}' mapped."))
            else:
                self.stdout.write(f"✓ Domain '{hostname}' already mapped.")

        self.stdout.write(self.style.SUCCESS("\nDone. http://localhost:8000/ is ready."))
