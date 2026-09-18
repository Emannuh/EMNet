# NetSuite-ISP — Architecture Document
**Version 2.0** | Updated to include Fiber/Fixed Subscriber Management subsystem

---

## 1. Platform Overview

NetSuite-ISP is a multi-tenant SaaS platform that ISPs subscribe to. It has
**three integrated subsystems** sharing one codebase, one database cluster,
and one AAA (authentication/authorization/accounting) layer.

| # | Subsystem | Who uses it | Core model |
|---|-----------|-------------|------------|
| 1 | **Tokenized WiFi / Captive Portal** | End-users buying hotspot time | Prepaid voucher, redeemed once |
| 2 | **LAN / Network Management** | ISP staff monitoring infrastructure | Devices, uptime, bandwidth |
| 3 | **Fiber / Fixed Subscriber Management** | ISP staff managing home/business lines | Recurring subscription account |

All three subsystems are multi-tenant: many ISPs share the same platform,
fully isolated from each other via Postgres schema-per-tenant (django-tenants).

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                           INTERNET / ISP NETWORK                     │
└────────────────┬─────────────────────────────────────┬───────────────┘
                 │                                     │
    ┌────────────▼────────────┐           ┌────────────▼────────────┐
    │   End-user device       │           │   ISP staff browser     │
    │  (hotspot client)       │           │  (admin dashboard)      │
    └────────────┬────────────┘           └────────────┬────────────┘
                 │                                     │
    ┌────────────▼────────────────────────────────────▼────────────┐
    │                      NGINX (reverse proxy)                    │
    │  /portal/* /payments/* /vouchers/* /sessions/*  →  FastAPI   │
    │  everything else                                →  Django     │
    │  X-Tenant-Schema header injected from subdomain              │
    └──────────────────┬───────────────────────────────────────────┘
                       │
         ┌─────────────┴────────────┐
         │                          │
┌────────▼────────┐       ┌────────▼────────┐
│  FastAPI        │       │  Django         │
│  Captive Portal │       │  Control Plane  │
│  (port 8001)    │       │  (port 8000)    │
│                 │       │                 │
│  - Splash page  │       │  - Tenant CRUD  │
│  - STK Push     │       │  - Network mgmt │
│  - Voucher redeem       │  - Portal admin │
│  - Session poll │       │  - Billing      │
└────────┬────────┘       │  - Subscriber   │
         │                │    management   │
         │                └────────┬────────┘
         │                         │
         └──────────┬──────────────┘
                    │
         ┌──────────▼──────────┐
         │   PostgreSQL        │
         │   + TimescaleDB     │
         │                     │
         │  public schema:     │
         │  tenants, users     │
         │                     │
         │  <isp_schema>:      │
         │  portal, billing,   │
         │  network, radius,   │
         │  subscribers        │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐      ┌─────────────────┐
         │   FreeRADIUS        │      │   Redis          │
         │   (AAA)             │      │   - Celery broker│
         │                     │      │   - Session cache│
         │  radcheck (both     │      └─────────────────┘
         │  vouchers AND       │
         │  PPPoE subscribers) │      ┌─────────────────┐
         │  radreply           │      │   Celery Workers │
         │  radacct            │      │   - SNMP polling │
         └─────────────────────┘      │   - Billing cron │
                                      │   - Suspend jobs │
                                      └─────────────────┘
```

---

## 3. Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Backend / control plane | Python 3.12, Django 4.2 | Multi-tenant admin, dashboards |
| Captive portal service | FastAPI 0.111 | High-traffic, public-facing |
| AAA | FreeRADIUS + SQL backend | Shared by vouchers AND PPPoE subscribers |
| Database | PostgreSQL 16 + TimescaleDB | Schema-per-tenant; hypertables for metrics |
| Async / scheduled | Celery 5 + Celery Beat + Redis 7 | SNMP polls, billing crons, suspend jobs |
| Multi-tenancy | django-tenants 3.6 | One Postgres schema per ISP |
| Frontend | Django templates + HTMX + Bootstrap 5 | No build pipeline for MVP |
| Payments | M-Pesa Daraja API (STK Push) | Architected to add other gateways later |
| Deployment | Docker Compose (dev) → ECS/AKS/k8s (prod) | |

---

## 4. Multi-Tenancy Model

- **Public schema**: `tenants_tenant`, `tenants_domain`, `accounts_user` (super-admins)
- **Per-ISP schema**: all domain models — portal, billing, network, radius, subscribers
- Tenant resolved by Nginx subdomain → `X-Tenant-Schema` header → Django middleware / FastAPI dependency
- FreeRADIUS uses a **separate `radius` database** (not schema-switched) — tenant isolation there is by `groupname` prefix convention (e.g. `acme_isp:planname`)

---

## 5. Subsystem 1 — Tokenized WiFi / Captive Portal

**Flow**: End-user connects to WiFi → NAS redirects to splash page → user buys a
voucher via M-Pesa → voucher redeemed → RADIUS credentials created →
user authenticated on network → session tracked.

**Key models** (per-tenant schema):
- `VoucherPlan` — purchasable time/data plan
- `Voucher` — single-use token (UUID code), status: pending → active → used/expired
- `WifiSession` — RADIUS accounting record tied to voucher
- `Payment` — M-Pesa STK Push record

**Key services**:
- FastAPI captive portal: splash, STK Push, voucher redeem, session poll
- Celery: M-Pesa callback processing, voucher expiry sweep

---

## 6. Subsystem 2 — LAN / Network Management

**Flow**: ISP registers network devices → Celery SNMP poller runs every 5 min →
status + bandwidth snapshots written to DB → dashboard shows uptime/bandwidth.

**Key models** (per-tenant schema):
- `Device` — router/switch/AP/ONT, IP, SNMP community
- `UptimeEvent` — status change log (up/down transitions)
- `BandwidthSnapshot` — TimescaleDB hypertable, ifInOctets/ifOutOctets per interface

**Key services**:
- Celery Beat: `poll_all_tenants` → `poll_tenant_devices` → `poll_single_device`
- Management command: `python manage.py poll_devices [--tenant x]`

---

## 7. Subsystem 3 — Fiber / Fixed Subscriber Management *(Phases 11–13)*

**Flow**: ISP creates a subscriber account → assigns a service plan + connection
type (PPPoE/static/DHCP) → CPE/ONT referenced → PPPoE credentials written to
`radcheck`/`radreply` → Celery billing cron generates monthly invoice →
M-Pesa STK Push collects payment → on non-payment, account suspended
(RADIUS credentials disabled) → on payment, reactivated.

**Key models** (per-tenant schema — new `apps/subscribers` app):
- `ServicePlan` — e.g. "20 Mbps unlimited, KES 3,500/month"; speed caps stored as RADIUS attributes
- `Subscriber` — customer record: name, contact, address, connection type, assigned IP, CPE serial, status
- `Subscription` — links subscriber to a service plan, tracks billing cycle, next due date
- `Invoice` — monthly invoice record: amount, due date, status (unpaid/paid/overdue)
- `InvoicePayment` — M-Pesa payment tied to an invoice (reuses M-Pesa service layer from billing app)

**Key services**:
- RADIUS integration: on subscription activation, write `radcheck` (PPPoE password or MAC) + `radreply` (speed caps via `Mikrotik-Rate-Limit` or `WISPr-Bandwidth-*`)
- Suspend/reactivate: toggle `radcheck` record disabled flag or move user out of active group
- Celery Beat: monthly invoice generation, overdue detection, auto-suspend after grace period
- IPAM: lightweight IP pool model to assign/release static IPs

**What it does NOT include (out of scope for now)**:
- OLT/GPON port provisioning (vendor-specific, e.g. Huawei MA5800 API)
- Full CPE zero-touch provisioning (TR-069/CWMP)
- Detailed per-subscriber bandwidth graphs (RADIUS accounting gives session data; deep per-subscriber graphing would need NetFlow/sFlow)

---

## 8. Security Considerations

- All secrets via environment variables, never hardcoded
- CSRF trusted origins explicitly set for all proxy ports
- JWT tokens for FastAPI captive portal sessions (24h expiry, enforced by RADIUS)
- Super-admin / ISP-admin / ISP-staff role separation enforced at view layer
- Tenant schema isolation: django-tenants prevents cross-tenant DB queries
- FreeRADIUS shared secret never exposed to frontend

---

## 9. Deployment

**Dev**: `docker compose up --build`
- All services in one compose file
- FreeRADIUS opt-in: `docker compose --profile radius up`
- Override file auto-runs migrations + `create_public_tenant` + Django dev server

**Prod target**: Container-based (ECS / AKS / k8s)
- Django + Celery + Portal each their own container/service
- Postgres on managed RDS/CloudSQL
- Redis on managed ElastiCache/MemoryStore
- FreeRADIUS on dedicated VM or container with UDP load balancing
