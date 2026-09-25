"""
Management command: test_stk_push

Sends a real M-Pesa STK Push to the specified phone number.
Use this to verify your Daraja credentials and callback URL work
correctly without going through the Django portal.

Usage:
  python manage.py test_stk_push 2547XXXXXXXX
  python manage.py test_stk_push 2547XXXXXXXX --amount 1
  python manage.py test_stk_push 2547XXXXXXXX --amount 10 --description "Test pay"
  python manage.py test_stk_push 2547XXXXXXXX --query <checkout_request_id>

Examples:
  # Send a KES 1 push to a Safaricom number
  python manage.py test_stk_push 254712345678

  # Send KES 10 with custom description
  python manage.py test_stk_push 254712345678 --amount 10 --description "ISP Test"

  # Query the status of a previous push (fallback check)
  python manage.py test_stk_push 254712345678 --query ws_CO_123456789
"""
import sys
import time

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings


class Command(BaseCommand):
    help = "Send a test M-Pesa STK Push to verify Daraja credentials"

    def add_arguments(self, parser):
        parser.add_argument(
            "phone",
            type=str,
            help="Phone number in 2547XXXXXXXX format",
        )
        parser.add_argument(
            "--amount",
            type=int,
            default=1,
            help="Amount in KES (default: 1)",
        )
        parser.add_argument(
            "--description",
            type=str,
            default="ISP Test",
            help="Transaction description shown on phone (max 13 chars)",
        )
        parser.add_argument(
            "--query",
            type=str,
            default="",
            metavar="CHECKOUT_ID",
            help="Query the status of an existing checkout request ID instead of sending a new push",
        )
        parser.add_argument(
            "--wait",
            action="store_true",
            default=False,
            help="After sending, poll for status every 5s for up to 60s",
        )

    def handle(self, *args, **options):
        phone       = options["phone"]
        amount      = options["amount"]
        description = options["description"]
        query_id    = options["query"]
        do_wait     = options["wait"]

        # ── Import M-Pesa client ──────────────────────────────────────────
        try:
            from apps.billing.mpesa import (
                stk_push, query_stk_status,
                MpesaNotConfigured, MpesaApiError,
            )
        except ImportError as exc:
            raise CommandError(f"Could not import mpesa module: {exc}")

        # ── Print current config ──────────────────────────────────────────
        self.stdout.write("\n" + "─" * 60)
        self.stdout.write(self.style.HTTP_INFO("M-Pesa Configuration"))
        self.stdout.write("─" * 60)
        self.stdout.write(f"  Environment    : {getattr(settings, 'MPESA_ENVIRONMENT', 'not set')}")
        self.stdout.write(f"  Shortcode      : {getattr(settings, 'MPESA_SHORTCODE', 'not set')}")
        key = getattr(settings, 'MPESA_CONSUMER_KEY', '') or 'not set'
        self.stdout.write(f"  Consumer Key   : {key[:8]}{'*' * max(0, len(key)-8) if len(key) > 8 else ''}")
        self.stdout.write(f"  Callback URL   : {getattr(settings, 'MPESA_CALLBACK_BASE_URL', 'not set')}/billing/mpesa/callback/")
        passkey = getattr(settings, 'MPESA_PASSKEY', '') or 'not set'
        self.stdout.write(f"  Passkey        : {passkey[:8]}{'*' * max(0, len(passkey)-8) if len(passkey) > 8 else ''}")
        self.stdout.write("─" * 60 + "\n")

        # ── Query mode ────────────────────────────────────────────────────
        if query_id:
            self.stdout.write(
                self.style.HTTP_INFO(f"Querying STK status for: {query_id}")
            )
            try:
                result = query_stk_status(query_id)
                self._print_query_result(result)
            except MpesaNotConfigured as exc:
                raise CommandError(str(exc))
            except MpesaApiError as exc:
                raise CommandError(f"Daraja API error: {exc}")
            return

        # ── Validate phone ────────────────────────────────────────────────
        if not phone.startswith("254") or len(phone) != 12:
            raise CommandError(
                f"Invalid phone '{phone}'. Must be 12 digits starting with 254 "
                f"(e.g. 254712345678)"
            )

        if amount < 1:
            raise CommandError("Amount must be at least KES 1.")

        # ── Send push ─────────────────────────────────────────────────────
        self.stdout.write(
            self.style.HTTP_INFO(
                f"Sending STK Push → phone={phone}  amount=KES {amount}  "
                f"desc='{description[:13]}'"
            )
        )

        try:
            result = stk_push(
                phone=phone,
                amount=amount,
                account_ref="TESTREF001",
                description=description[:13],
                callback_path="/billing/mpesa/callback/",
            )
        except MpesaNotConfigured as exc:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR("✗ M-Pesa NOT configured"))
            self.stdout.write(self.style.ERROR(f"  {exc}"))
            self.stdout.write("")
            self.stdout.write("  Fix: Set these in your .env file:")
            for var in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET",
                        "MPESA_PASSKEY", "MPESA_SHORTCODE", "MPESA_CALLBACK_BASE_URL"):
                val = getattr(settings, var, "") or ""
                status = "✓ set" if val and val not in ("change-me", "") else "✗ MISSING"
                self.stdout.write(f"    {var}: {status}")
            sys.exit(1)
        except MpesaApiError as exc:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(f"✗ Daraja API error: {exc}"))
            if hasattr(exc, "response_body") and exc.response_body:
                self.stdout.write(f"  Response: {exc.response_body}")
            sys.exit(1)

        # ── Success ───────────────────────────────────────────────────────
        checkout_id = result.get("CheckoutRequestID", "")
        merchant_id = result.get("MerchantRequestID", "")
        message     = result.get("CustomerMessage", "")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✓ STK Push sent successfully!"))
        self.stdout.write(f"  CheckoutRequestID  : {checkout_id}")
        self.stdout.write(f"  MerchantRequestID  : {merchant_id}")
        self.stdout.write(f"  Customer message   : {message}")
        self.stdout.write("")
        self.stdout.write(
            "  The customer should now see a PIN prompt on their phone."
        )
        self.stdout.write(
            f"  To manually check the result:\n"
            f"    python manage.py test_stk_push {phone} --query {checkout_id}"
        )

        # ── Optional polling ──────────────────────────────────────────────
        if do_wait and checkout_id:
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("Polling for result (--wait)…"))
            for attempt in range(1, 13):  # up to 60s
                time.sleep(5)
                self.stdout.write(f"  [{attempt * 5}s] Checking status…", ending="\r")
                self.stdout.flush()
                try:
                    status_result = query_stk_status(checkout_id)
                    rc = int(status_result.get("ResultCode", -1))
                    if rc == 1032:
                        continue  # still processing
                    self.stdout.write("")
                    self._print_query_result(status_result)
                    return
                except MpesaApiError:
                    continue
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Timed out waiting for result. "
                    "The callback will arrive asynchronously when the customer approves."
                )
            )

    def _print_query_result(self, result: dict):
        rc   = int(result.get("ResultCode", -1))
        desc = result.get("ResultDesc", "")
        self.stdout.write("")
        if rc == 0:
            self.stdout.write(self.style.SUCCESS(f"✓ Payment SUCCESSFUL — {desc}"))
        elif rc == 1032:
            self.stdout.write(self.style.WARNING(f"⏳ Still processing — {desc}"))
        elif rc == 1037:
            self.stdout.write(self.style.WARNING(f"⏰ Timed out — {desc}"))
        else:
            self.stdout.write(self.style.ERROR(f"✗ Payment FAILED (code {rc}) — {desc}"))
        self.stdout.write(f"  Full response: {result}")
        self.stdout.write("")
