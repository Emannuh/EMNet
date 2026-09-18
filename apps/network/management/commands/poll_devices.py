"""
Management command to manually trigger the SNMP device poll.
Usage:
    python manage.py poll_devices               # poll all tenants
    python manage.py poll_devices --tenant acme # poll one tenant by schema name
"""
from django.core.management.base import BaseCommand

from apps.network.tasks import poll_all_tenants, poll_tenant_devices


class Command(BaseCommand):
    help = "Trigger SNMP device polling (runs tasks synchronously for debugging)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            type=str,
            default=None,
            help="Schema name of a specific tenant to poll (default: all tenants)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help="Dispatch as Celery tasks instead of running synchronously",
        )

    def handle(self, *args, **options):
        schema = options["tenant"]
        run_async = options["run_async"]

        if schema:
            self.stdout.write(f"Polling devices for tenant: {schema}")
            if run_async:
                poll_tenant_devices.delay(schema)
                self.stdout.write(self.style.SUCCESS("Task dispatched to Celery."))
            else:
                poll_tenant_devices(schema)
                self.stdout.write(self.style.SUCCESS("Done."))
        else:
            self.stdout.write("Polling all active tenants…")
            if run_async:
                poll_all_tenants.delay()
                self.stdout.write(self.style.SUCCESS("Task dispatched to Celery."))
            else:
                poll_all_tenants()
                self.stdout.write(self.style.SUCCESS("Done."))
