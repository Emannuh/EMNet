"""
One-time setup script: creates the public tenant and maps localhost to it.
Run with: docker exec -it netsuite_django python scripts/create_public_tenant.py
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.tenants.models import Tenant, Domain

# Create the public tenant (schema_name MUST be 'public')
tenant, created = Tenant.objects.get_or_create(
    schema_name="public",
    defaults={
        "name": "NetSuite-ISP Platform",
        "contact_email": "platform@netsuite.io",
    },
)
if created:
    print("✓ Public tenant created.")
else:
    print("✓ Public tenant already exists.")

# Map localhost (and 127.0.0.1) to the public tenant
for hostname in ["localhost", "127.0.0.1"]:
    domain, created = Domain.objects.get_or_create(
        domain=hostname,
        defaults={"tenant": tenant, "is_primary": hostname == "localhost"},
    )
    if created:
        print(f"✓ Domain '{hostname}' mapped to public tenant.")
    else:
        print(f"✓ Domain '{hostname}' already mapped.")

print("\nDone. You can now access http://localhost:8000/")
