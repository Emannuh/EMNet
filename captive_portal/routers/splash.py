"""
Splash page router.
The NAS/router redirects unauthenticated clients here.
Returns a self-contained HTML page — no separate frontend build needed.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from captive_portal.core.tenant import get_tenant_schema

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def splash_page(
    mac: str = Query("", description="Client MAC address passed by NAS"),
    ip: str = Query("", description="Client IP address passed by NAS"),
    url: str = Query("", description="Original URL the client was trying to reach"),
    tenant_schema: str = Depends(get_tenant_schema),
):
    """
    Entry point for captive portal redirection.
    Renders the full voucher-purchase / redemption splash page.
    """
    redirect_url = url or "http://example.com"
    html = _render_splash(
        tenant_schema=tenant_schema,
        mac=mac,
        client_ip=ip,
        redirect_url=redirect_url,
    )
    return HTMLResponse(content=html)


# ── HTML renderer ─────────────────────────────────────────────────────────────

def _render_splash(
    tenant_schema: str,
    mac: str,
    client_ip: str,
    redirect_url: str,
) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>WiFi Access Portal</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <style>
    body {{
      min-height: 100vh;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .portal-card {{
      max-width: 440px;
      width: 100%;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 25px 50px rgba(0,0,0,0.4);
    }}
    .portal-header {{
      background: linear-gradient(135deg, #0f3460, #533483);
      padding: 2rem;
      text-align: center;
      color: white;
    }}
    .plan-card {{
      cursor: pointer;
      border: 2px solid #dee2e6;
      border-radius: 10px;
      padding: 0.875rem;
      transition: all 0.15s ease;
    }}
    .plan-card:hover {{ border-color: #0d6efd; background: #f0f7ff; }}
    .plan-card.selected {{ border-color: #0d6efd; background: #e7f1ff; }}
    .plan-price {{ font-size: 1.4rem; font-weight: 700; color: #0d6efd; }}
    .step {{ display: none; }}
    .step.active {{ display: block; }}
    .spinner-border-sm {{ width: 1rem; height: 1rem; }}
    .alert-sm {{ padding: .4rem .75rem; font-size: .875rem; }}
    .badge-pill {{ border-radius: 50rem; }}
    .step-indicator {{
      display: flex;
      justify-content: center;
      gap: .5rem;
      margin-bottom: 1.5rem;
    }}
    .step-dot {{
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #dee2e6;
      transition: background .2s;
    }}
    .step-dot.active {{ background: #0d6efd; }}
    .step-dot.done {{ background: #198754; }}
  </style>
</head>
<body>

<div class="portal-card bg-white">

  <!-- Header -->
  <div class="portal-header">
    <i class="bi bi-wifi fs-1 mb-2 d-block"></i>
    <h4 class="mb-0 fw-bold">WiFi Access Portal</h4>
    <small class="opacity-75">Buy a voucher to get online instantly</small>
  </div>

  <!-- Body -->
  <div class="p-4">

    <!-- Step indicator -->
    <div class="step-indicator">
      <div class="step-dot active" id="dot-1"></div>
      <div class="step-dot" id="dot-2"></div>
      <div class="step-dot" id="dot-3"></div>
      <div class="step-dot" id="dot-4"></div>
    </div>

    <!-- ── Step 1: Choose a plan ────────────────────────────────────── -->
    <div class="step active" id="step-1">
      <h6 class="fw-bold mb-3">
        <i class="bi bi-grid me-2 text-primary"></i>Choose a Plan
      </h6>

      <div id="plans-container">
        <!-- Plans are loaded here by JS -->
        <div class="text-center py-4 text-muted" id="plans-loading">
          <span class="spinner-border spinner-border-sm me-2"></span>Loading plans…
        </div>
      </div>

      <div class="alert alert-danger alert-sm mt-3 d-none" id="plans-error"></div>

      <button class="btn btn-primary w-100 mt-3" id="btn-choose-plan" disabled
              onclick="goToStep2()">
        Continue <i class="bi bi-arrow-right ms-1"></i>
      </button>
    </div>

    <!-- ── Step 2: Enter phone number ──────────────────────────────── -->
    <div class="step" id="step-2">
      <h6 class="fw-bold mb-1">
        <i class="bi bi-phone me-2 text-primary"></i>M-Pesa Payment
      </h6>
      <p class="text-muted small mb-3">
        Enter your Safaricom number to receive the payment prompt.
      </p>

      <div class="mb-3">
        <label class="form-label">Selected Plan</label>
        <div class="p-2 bg-light rounded small" id="selected-plan-summary">—</div>
      </div>

      <div class="mb-4">
        <label class="form-label">Phone Number <span class="text-danger">*</span></label>
        <div class="input-group">
          <span class="input-group-text">🇰🇪 +254</span>
          <input type="tel" id="phone-input" class="form-control"
                 placeholder="7XX XXX XXX" maxlength="9"
                 oninput="validatePhone()">
        </div>
        <div class="form-text">Format: 07XXXXXXXX or 7XXXXXXXX</div>
        <div class="invalid-feedback" id="phone-error"></div>
      </div>

      <div class="alert alert-danger alert-sm d-none" id="stk-error"></div>

      <div class="d-flex gap-2">
        <button class="btn btn-outline-secondary" onclick="goToStep(1)">
          <i class="bi bi-arrow-left me-1"></i>Back
        </button>
        <button class="btn btn-success flex-grow-1" id="btn-pay" onclick="initiatePay()" disabled>
          <i class="bi bi-phone me-1"></i>Send Payment Request
        </button>
      </div>
    </div>

    <!-- ── Step 3: Waiting for payment ────────────────────────────── -->
    <div class="step" id="step-3">
      <div class="text-center py-3">
        <div class="spinner-border text-success mb-3" role="status"></div>
        <h6 class="fw-bold">Check your phone</h6>
        <p class="text-muted small mb-1">
          A payment prompt has been sent to your M-Pesa number.<br>
          Enter your PIN to complete the payment.
        </p>
        <div class="alert alert-info alert-sm mt-3" id="stk-info">
          Waiting for payment confirmation…
        </div>
      </div>

      <hr>

      <h6 class="fw-semibold mb-2 small text-muted text-uppercase">
        Already have a voucher code?
      </h6>
      <div class="input-group mb-3">
        <input type="text" id="voucher-input" class="form-control"
               placeholder="Paste your voucher code here">
        <button class="btn btn-primary" onclick="redeemVoucher()">
          <i class="bi bi-check-lg me-1"></i>Redeem
        </button>
      </div>
      <div class="alert alert-danger alert-sm d-none" id="redeem-error"></div>

      <button class="btn btn-outline-secondary btn-sm w-100 mt-1"
              onclick="goToStep(1)">
        <i class="bi bi-arrow-left me-1"></i>Start over
      </button>
    </div>

    <!-- ── Step 4: Connected ───────────────────────────────────────── -->
    <div class="step" id="step-4">
      <div class="text-center py-3">
        <i class="bi bi-check-circle-fill text-success fs-1 mb-3 d-block"></i>
        <h5 class="fw-bold text-success">You're Connected!</h5>
        <p class="text-muted small mb-3">
          Your WiFi session has started. Enjoy browsing!
        </p>
        <div class="alert alert-success alert-sm" id="session-info"></div>
        <a href="{redirect_url}" class="btn btn-primary mt-2 w-100">
          <i class="bi bi-globe me-2"></i>Go to the web
        </a>
      </div>
    </div>

  </div><!-- /body -->

  <!-- Footer -->
  <div class="text-center pb-3 text-muted" style="font-size:.75rem;">
    <span>Powered by <strong>Emmsuite ISP</strong></span>
  </div>

</div><!-- /portal-card -->

<script>
  // ── State ────────────────────────────────────────────────────────────────
  const STATE = {{
    mac: "{mac}",
    ip: "{client_ip}",
    tenantSchema: "{tenant_schema}",
    selectedPlanId: null,
    selectedPlanName: "",
    selectedPlanPrice: "",
    checkoutRequestId: null,
  }};

  // ── Step navigation ──────────────────────────────────────────────────────
  function goToStep(n) {{
    document.querySelectorAll(".step").forEach((el, i) => {{
      el.classList.toggle("active", i + 1 === n);
    }});
    for (let i = 1; i <= 4; i++) {{
      const dot = document.getElementById("dot-" + i);
      if (i < n)  dot.className = "step-dot done";
      else if (i === n) dot.className = "step-dot active";
      else dot.className = "step-dot";
    }}
  }}

  function goToStep2() {{
    if (!STATE.selectedPlanId) return;
    document.getElementById("selected-plan-summary").textContent =
      STATE.selectedPlanName + " — KES " + STATE.selectedPlanPrice;
    goToStep(2);
  }}

  // ── Step 1: Load plans ───────────────────────────────────────────────────
  async function loadPlans() {{
    try {{
      // TODO (integration): replace with real DB fetch via internal API
      // For now we show demo plans so the UI can be tested end-to-end
      const plans = [
        {{ id: 1, name: "30 Min Browsing", duration_minutes: 30, data_mb: null, price_kes: "10.00", is_active: true }},
        {{ id: 2, name: "1 Hour",          duration_minutes: 60, data_mb: null, price_kes: "20.00", is_active: true }},
        {{ id: 3, name: "500 MB Data",     duration_minutes: null, data_mb: 500, price_kes: "30.00", is_active: true }},
        {{ id: 4, name: "Daily (24 hrs)",  duration_minutes: 1440, data_mb: null, price_kes: "50.00", is_active: true }},
      ];

      document.getElementById("plans-loading").style.display = "none";
      const container = document.getElementById("plans-container");

      plans.filter(p => p.is_active).forEach(plan => {{
        const label = plan.duration_minutes
          ? formatDuration(plan.duration_minutes)
          : (plan.data_mb >= 1024 ? (plan.data_mb/1024).toFixed(0)+"GB" : plan.data_mb+"MB");

        const div = document.createElement("div");
        div.className = "plan-card mb-2 d-flex align-items-center justify-content-between";
        div.dataset.planId = plan.id;
        div.innerHTML = `
          <div>
            <div class="fw-semibold">${{plan.name}}</div>
            <small class="text-muted">${{label}}</small>
          </div>
          <div class="plan-price">KES ${{plan.price_kes}}</div>
        `;
        div.onclick = () => selectPlan(plan.id, plan.name, plan.price_kes, div);
        container.appendChild(div);
      }});

    }} catch (e) {{
      document.getElementById("plans-error").textContent = "Failed to load plans. Please refresh.";
      document.getElementById("plans-error").classList.remove("d-none");
    }}
  }}

  function formatDuration(minutes) {{
    if (minutes >= 1440) return (minutes / 1440) + " day(s)";
    if (minutes >= 60)   return (minutes / 60) + " hr";
    return minutes + " min";
  }}

  function selectPlan(id, name, price, el) {{
    document.querySelectorAll(".plan-card").forEach(c => c.classList.remove("selected"));
    el.classList.add("selected");
    STATE.selectedPlanId = id;
    STATE.selectedPlanName = name;
    STATE.selectedPlanPrice = price;
    document.getElementById("btn-choose-plan").disabled = false;
  }}

  // ── Step 2: Phone validation ─────────────────────────────────────────────
  function validatePhone() {{
    const raw = document.getElementById("phone-input").value.replace(/\\s/g, "");
    // Accept 07XXXXXXXX (9 digits) or 7XXXXXXXX (9 digits starting 7)
    const valid = /^(0?7\\d{{8}})$/.test(raw);
    document.getElementById("btn-pay").disabled = !valid;
    return valid;
  }}

  function buildSafaricomNumber() {{
    let v = document.getElementById("phone-input").value.replace(/\\s/g, "");
    if (v.startsWith("0")) v = v.slice(1);  // strip leading 0
    return "254" + v;                       // → 2547XXXXXXXX
  }}

  // ── Step 2: Initiate STK Push ────────────────────────────────────────────
  async function initiatePay() {{
    if (!validatePhone()) return;

    const btn = document.getElementById("btn-pay");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Sending…';
    document.getElementById("stk-error").classList.add("d-none");

    try {{
      const resp = await fetch("/payments/stk-push", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/json",
          "X-Tenant-Schema": STATE.tenantSchema,
        }},
        body: JSON.stringify({{
          phone_number: buildSafaricomNumber(),
          plan_id: STATE.selectedPlanId,
          mac_address: STATE.mac || "00:00:00:00:00:00",
        }}),
      }});

      if (!resp.ok) {{
        const err = await resp.json();
        throw new Error(err.detail || "Payment request failed");
      }}

      const data = await resp.json();
      STATE.checkoutRequestId = data.checkout_request_id;
      goToStep(3);

    }} catch (e) {{
      document.getElementById("stk-error").textContent = e.message;
      document.getElementById("stk-error").classList.remove("d-none");
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-phone me-1"></i>Send Payment Request';
    }}
  }}

  // ── Step 3: Redeem voucher code ──────────────────────────────────────────
  async function redeemVoucher() {{
    const code = document.getElementById("voucher-input").value.trim();
    if (!code) return;

    document.getElementById("redeem-error").classList.add("d-none");

    try {{
      const resp = await fetch("/vouchers/redeem", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/json",
          "X-Tenant-Schema": STATE.tenantSchema,
        }},
        body: JSON.stringify({{
          voucher_code: code,
          mac_address: STATE.mac || "00:00:00:00:00:00",
          client_ip: STATE.ip || "0.0.0.0",
        }}),
      }});

      if (!resp.ok) {{
        const err = await resp.json();
        throw new Error(err.detail || "Redemption failed");
      }}

      const data = await resp.json();
      document.getElementById("session-info").textContent = data.message;
      goToStep(4);

    }} catch (e) {{
      document.getElementById("redeem-error").textContent = e.message;
      document.getElementById("redeem-error").classList.remove("d-none");
    }}
  }}

  // ── Boot ─────────────────────────────────────────────────────────────────
  loadPlans();
</script>

</body>
</html>"""
