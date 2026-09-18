"""
Management command to create and fully seed the DeeNet demo tenant.

Creates:
  - Tenant: deenet / DeeNet Communications
  - Domain: deenet.localhost
  - ISP admin user
  - 6 voucher plans (tokenised wireless)
  - 4 fiber service plans
  - 1 IP pool with 18 addresses
  - 6 network devices (routers, switches, APs, ONT)
  - 5 fiber subscribers with active subscriptions
  - 5 unpaid invoices (one per subscriber)
  - 4 sample vouchers

Usage:
    python manage.py seed_deenet
    python manage.py seed_deenet --reset   # drops and recreates
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "Create and seed the DeeNet demo tenant end-to-end"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing deenet tenant and recreate from scratch",
        )

    def handle(self, *args, **options):
        from apps.tenants.models import Tenant, Domain

        # ── Optional reset ────────────────────────────────────────────────
        if options["reset"]:
            try:
                old = Tenant.objects.get(schema_name="deenet")
                self.stdout.write("Dropping existing deenet tenant...")
                old.delete(force_drop=True)
                self.stdout.write(self.style.WARNING("Old tenant dropped."))
            except Tenant.DoesNotExist:
                pass
            User.objects.filter(email="admin@deenet.co.ke").delete()

        # ── Guard: don't recreate if already exists ───────────────────────
        if Tenant.objects.filter(schema_name="deenet").exists():
            self.stdout.write(self.style.WARNING(
                "deenet tenant already exists. Run with --reset to recreate."
            ))
            return

        # ── 1. Create tenant + domain + admin user ────────────────────────
        self.stdout.write("Creating DeeNet tenant...")
        with transaction.atomic():
            tenant = Tenant(
                schema_name="deenet",
                name="DeeNet Communications",
                contact_email="admin@deenet.co.ke",
                contact_phone="+254700000001",
            )
            tenant.save()  # triggers Postgres schema creation

            Domain.objects.create(
                domain="deenet.localhost",
                tenant=tenant,
                is_primary=True,
            )

            admin = User.objects.create_user(
                email="admin@deenet.co.ke",
                password="Deenet2026!",
                full_name="DeeNet Admin",
                role=User.Role.ISP_ADMIN,
                is_staff=True,
            )

        self.stdout.write(self.style.SUCCESS(
            f"  Tenant schema: deenet"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"  Domain: deenet.localhost"
        ))
        self.stdout.write(self.style.SUCCESS(
            f"  Admin: {admin.email}  password: Deenet2026!"
        ))

        # ── 2. Seed tenant schema ─────────────────────────────────────────
        from django_tenants.utils import schema_context

        with schema_context("deenet"):
            self._seed_voucher_plans()
            self._seed_service_plans_and_pools()
            self._seed_devices()
            self._seed_subscribers()
            self._seed_vouchers()

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 55))
        self.stdout.write(self.style.SUCCESS("  DeeNet seeded successfully!"))
        self.stdout.write(self.style.SUCCESS("=" * 55))
        self.stdout.write("")
        self.stdout.write("  Add to C:\\Windows\\System32\\drivers\\etc\\hosts:")
        self.stdout.write("  127.0.0.1   deenet.localhost")
        self.stdout.write("")
        self.stdout.write("  Login at: http://deenet.localhost:8080/accounts/login/")
        self.stdout.write("  Email   : admin@deenet.co.ke")
        self.stdout.write("  Password: Deenet2026!")
        self.stdout.write("")

    # ── Voucher plans ─────────────────────────────────────────────────────

    def _seed_voucher_plans(self):
        from apps.portal.models import VoucherPlan
        plans = [
            dict(name="30 Min Hotspot",  duration_minutes=30,   data_mb=None, price_kes=10,  is_active=True),
            dict(name="1 Hour Hotspot",  duration_minutes=60,   data_mb=None, price_kes=20,  is_active=True),
            dict(name="3 Hours Hotspot", duration_minutes=180,  data_mb=None, price_kes=50,  is_active=True),
            dict(name="Daily Pass",      duration_minutes=1440, data_mb=None, price_kes=100, is_active=True),
            dict(name="500 MB Data",     duration_minutes=None, data_mb=500,  price_kes=30,  is_active=True),
            dict(name="1 GB Data",       duration_minutes=None, data_mb=1024, price_kes=55,  is_active=True),
        ]
        for p in plans:
            VoucherPlan.objects.get_or_create(name=p["name"], defaults=p)
        self.stdout.write(f"  Voucher plans: {VoucherPlan.objects.count()}")

    # ── Service plans + IP pool ───────────────────────────────────────────

    def _seed_service_plans_and_pools(self):
        from apps.subscribers.models import ServicePlan, IpPool, IpAddress

        plans = [
            dict(name="Home 10 Mbps",            connection_type="pppoe",   download_mbps=10,  upload_mbps=5,  price_kes=2500, billing_cycle="monthly",  grace_days=3),
            dict(name="Home 20 Mbps",             connection_type="pppoe",   download_mbps=20,  upload_mbps=10, price_kes=3500, billing_cycle="monthly",  grace_days=3),
            dict(name="Business 50 Mbps",         connection_type="pppoe",   download_mbps=50,  upload_mbps=25, price_kes=8000, billing_cycle="monthly",  grace_days=5),
            dict(name="Business Static IP 20Mbps",connection_type="static",  download_mbps=20,  upload_mbps=20, price_kes=6000, billing_cycle="monthly",  grace_days=5),
        ]
        for p in plans:
            ServicePlan.objects.get_or_create(name=p["name"], defaults={**p, "is_active": True})

        pool, _ = IpPool.objects.get_or_create(
            name="Residential Block A",
            defaults=dict(
                network="192.168.10.0/24",
                gateway="192.168.10.1",
                dns_primary="8.8.8.8",
                dns_secondary="8.8.4.4",
                is_active=True,
            ),
        )
        for i in range(2, 20):
            IpAddress.objects.get_or_create(
                address=f"192.168.10.{i}",
                defaults=dict(pool=pool, status="available"),
            )
        self.stdout.write(f"  Service plans: {ServicePlan.objects.count()}  |  IP pool: {IpAddress.objects.count()} addresses")

    # ── Network devices ───────────────────────────────────────────────────

    def _seed_devices(self):
        from apps.network.models import Device
        devices = [
            dict(name="Core Router",       ip_address="10.0.0.1",    device_type="router", location="Server Room",   status="up",      last_seen=timezone.now(), snmp_community="public", snmp_version="2c"),
            dict(name="Distribution SW1",  ip_address="10.0.0.2",    device_type="switch", location="Server Room",   status="up",      last_seen=timezone.now(), snmp_community="public", snmp_version="2c"),
            dict(name="AP Block A",        ip_address="192.168.1.10", device_type="ap",     location="Block A Roof",  status="up",      last_seen=timezone.now(), snmp_community="public", snmp_version="2c"),
            dict(name="AP Block B",        ip_address="192.168.1.11", device_type="ap",     location="Block B Roof",  status="down",    last_seen=None,           snmp_community="public", snmp_version="2c"),
            dict(name="OLT Main",          ip_address="10.0.0.10",   device_type="ont",    location="Exchange Room", status="up",      last_seen=timezone.now(), snmp_community="public", snmp_version="2c"),
            dict(name="AP Market Centre",  ip_address="192.168.2.5",  device_type="ap",     location="Market Centre", status="unknown", last_seen=None,           snmp_community="public", snmp_version="2c"),
        ]
        for d in devices:
            Device.objects.get_or_create(ip_address=d["ip_address"], defaults=d)
        self.stdout.write(f"  Network devices: {Device.objects.count()}")

    # ── Fiber subscribers ─────────────────────────────────────────────────

    def _seed_subscribers(self):
        from apps.subscribers.models import (
            ServicePlan, Subscriber, Subscription, Invoice
        )

        records = [
            ("John Kamau",     "0712345678", "john.kamau",     "Pass1234!", "Home 20 Mbps",             "Apt 5, Ngong Road, Nairobi"),
            ("Mary Wanjiku",   "0723456789", "mary.wanjiku",   "Pass1234!", "Home 10 Mbps",             "House 12, Kiambu Road"),
            ("Acme Ltd",       "0734567890", "acme.ltd",       "Pass1234!", "Business 50 Mbps",         "Westlands, Nairobi"),
            ("Peter Odhiambo", "0745678901", "peter.odhiambo", "Pass1234!", "Business Static IP 20Mbps","Industrial Area, Nairobi"),
            ("Grace Muthoni",  "0756789012", "grace.muthoni",  "Pass1234!", "Home 20 Mbps",             "Thika Road, Apt 3"),
        ]

        for full_name, phone, username, pwd, plan_name, address in records:
            plan = ServicePlan.objects.get(name=plan_name)
            sub, created = Subscriber.objects.get_or_create(
                pppoe_username=username,
                defaults=dict(
                    full_name=full_name,
                    phone=phone,
                    pppoe_password=pwd,
                    address=address,
                    status="active",
                ),
            )
            if created:
                subscription = Subscription.objects.create(
                    subscriber=sub,
                    plan=plan,
                    status="active",
                    start_date=date.today(),
                    next_due_date=plan.next_due_date(date.today()),
                )
                Invoice.objects.create(
                    subscription=subscription,
                    amount_kes=plan.price_kes,
                    due_date=date.today(),
                    period_start=date.today(),
                    period_end=date.today() + timedelta(days=30),
                    status="unpaid",
                )

        self.stdout.write(f"  Subscribers: {Subscriber.objects.count()}  |  Invoices: {Invoice.objects.count()}")

    # ── Sample vouchers ───────────────────────────────────────────────────

    def _seed_vouchers(self):
        from apps.portal.models import VoucherPlan, Voucher
        plan_1hr   = VoucherPlan.objects.get(name="1 Hour Hotspot")
        plan_daily = VoucherPlan.objects.get(name="Daily Pass")
        plan_500mb = VoucherPlan.objects.get(name="500 MB Data")

        vouchers = [
            Voucher(plan=plan_1hr,   status="active",  phone_number="0798765432"),
            Voucher(plan=plan_1hr,   status="used",    phone_number="0787654321"),
            Voucher(plan=plan_daily, status="pending", phone_number="0776543210"),
            Voucher(plan=plan_daily, status="active",  phone_number="0765432109"),
            Voucher(plan=plan_500mb, status="active",  phone_number="0754321098"),
            Voucher(plan=plan_500mb, status="expired", phone_number="0743210987"),
        ]
        for v in vouchers:
            v.save()

        self.stdout.write(f"  Vouchers: {Voucher.objects.count()}")
