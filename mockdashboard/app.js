// ===== EMBEDDED SEED FALLBACK =====
const EMBEDDED_SEED = {
  "$schema_version": "1.0",
  "merchant": {"name": "Sharma General Store", "merchant_id": "acc_DEMO0000000001", "currency": "INR", "timezone": "Asia/Kolkata"},
  "today": "2026-09-03",
  "scenarios": [
    {
      "id": "settlement_lower_than_gross",
      "title": "Settlement is lower than the day's collection",
      "page": "settlements",
      "default": true,
      "settlements": [
        {"id": "setl_DEMO001", "status": "processed", "period_start": "2026-09-01", "period_end": "2026-09-01", "settled_on": "2026-09-03", "utr": "UTRDEMO0001", "gross_amount": 1000000, "fees": 20000, "tax": 3600, "refunds": 50000, "adjustments": 0, "net_amount": 926400},
        {"id": "setl_DEMO002", "status": "processed", "period_start": "2026-08-31", "period_end": "2026-08-31", "settled_on": "2026-09-02", "utr": "UTRDEMO0002", "gross_amount": 450000, "fees": 9000, "tax": 1620, "refunds": 0, "adjustments": 0, "net_amount": 439380},
        {"id": "setl_DEMO003", "status": "pending", "period_start": "2026-09-02", "period_end": "2026-09-02", "settled_on": null, "utr": null, "gross_amount": 720000, "fees": 14400, "tax": 2592, "refunds": 0, "adjustments": -1500, "net_amount": 701508}
      ],
      "payments": [
        {"id": "pay_DEMO0001", "amount": 250000, "status": "captured", "method": "upi", "created_at": "2026-09-01T10:14:00+05:30", "customer_name": "Rohit Verma", "customer_contact": "+919812345678", "description": "Grocery order #1182", "fee": 5000, "tax": 900},
        {"id": "pay_DEMO0002", "amount": 400000, "status": "captured", "method": "card", "created_at": "2026-09-01T12:02:00+05:30", "customer_name": "Anita Desai", "customer_contact": "+919900112233", "description": "Bulk order #1183", "fee": 8000, "tax": 1440},
        {"id": "pay_DEMO0003", "amount": 350000, "status": "captured", "method": "netbanking", "created_at": "2026-09-01T17:41:00+05:30", "customer_name": "Imran Shaikh", "customer_contact": "+919765432100", "description": "Festival hamper #1184", "fee": 7000, "tax": 1260}
      ],
      "refunds": [{"id": "rfnd_DEMO001", "payment_id": "pay_DEMO0002", "amount": 50000, "type": "partial", "status": "processed", "created_at": "2026-09-01T18:20:00+05:30", "reason": "Two items out of stock"}],
      "failed_payments": [],
      "payment_links": []
    },
    {
      "id": "multiple_failed_payments",
      "title": "Several payments failed yesterday",
      "page": "payments",
      "settlements": [],
      "payments": [],
      "refunds": [],
      "failed_payments": [
        {"id": "pay_DEMOF001", "amount": 120000, "status": "failed", "method": "card", "created_at": "2026-09-02T11:05:00+05:30", "customer_name": "Kavita Rao", "customer_contact": "+919845001122", "description": "Order #1190", "error_description": "Payment was not completed at the bank's page."},
        {"id": "pay_DEMOF002", "amount": 89900, "status": "failed", "method": "upi", "created_at": "2026-09-02T13:44:00+05:30", "customer_name": "Suresh Nair", "customer_contact": "+919812009988", "description": "Order #1191", "error_description": "Customer closed the UPI app before approving."},
        {"id": "pay_DEMOF003", "amount": 250000, "status": "failed", "method": "card", "created_at": "2026-09-02T16:12:00+05:30", "customer_name": "Priya Menon", "customer_contact": "+919700554433", "description": "Order #1192", "error_description": "The OTP entered was incorrect too many times."},
        {"id": "pay_DEMOF004", "amount": 45000, "status": "failed", "method": "wallet", "created_at": "2026-09-02T19:30:00+05:30", "customer_name": "Deepak Joshi", "customer_contact": "+919611223344", "description": "Order #1193", "error_description": "The wallet did not have enough balance."}
      ],
      "payment_links": []
    },
    {"id": "full_and_partial_refunds", "title": "One full refund and one partial refund", "page": "refunds", "settlements": [], "payments": [
      {"id": "pay_DEMO0101", "amount": 180000, "status": "refunded", "method": "upi", "created_at": "2026-08-30T09:20:00+05:30", "customer_name": "Meera Iyer", "customer_contact": "+919833445566", "description": "Order #1170"},
      {"id": "pay_DEMO0102", "amount": 600000, "status": "partially_refunded", "method": "card", "created_at": "2026-08-30T15:00:00+05:30", "customer_name": "Arjun Bhatt", "customer_contact": "+919922334455", "description": "Order #1171"}
    ], "refunds": [
      {"id": "rfnd_DEMO101", "payment_id": "pay_DEMO0101", "amount": 180000, "type": "full", "status": "processed", "created_at": "2026-08-30T11:00:00+05:30", "reason": "Item damaged in transit"},
      {"id": "rfnd_DEMO102", "payment_id": "pay_DEMO0102", "amount": 150000, "type": "partial", "status": "pending", "created_at": "2026-08-31T10:30:00+05:30", "reason": "One of four items returned"}
    ], "failed_payments": [], "payment_links": []},
    {"id": "payment_link_creation", "title": "Creating a payment link", "page": "payment_links", "settlements": [], "payments": [], "refunds": [], "failed_payments": [], "payment_links": [
      {"id": "plink_DEMO001", "amount": 150000, "status": "paid", "description": "Custom cake order", "created_at": "2026-08-28T12:00:00+05:30", "expire_by": "2026-08-31T12:00:00+05:30", "customer_name": "Nikhil Gupta", "customer_contact": "+919812340000", "short_url": "https://rzp.io/l/DEMOLINK1"},
      {"id": "plink_DEMO002", "amount": 320000, "status": "issued", "description": "Catering advance", "created_at": "2026-09-01T09:00:00+05:30", "expire_by": "2026-09-08T09:00:00+05:30", "customer_name": "Ritu Sharma", "customer_contact": "+919845556677", "short_url": "https://rzp.io/l/DEMOLINK2"}
    ]},
    {"id": "empty_state", "title": "Empty state — no transactions yet", "page": "payments", "settlements": [], "payments": [], "refunds": [], "failed_payments": [], "payment_links": []},
    {"id": "api_failure", "title": "Dashboard data could not load", "page": "settlements", "simulate_error": {"code": "SERVER_ERROR", "message": "We are unable to fetch settlements right now. Please retry."}, "settlements": [], "payments": [], "refunds": [], "failed_payments": [], "payment_links": []},
    {"id": "incomplete_data", "title": "Settlement row with missing fields", "page": "settlements", "settlements": [{"id": "setl_DEMO900", "status": "processed", "period_start": "2026-08-29", "period_end": "2026-08-29", "settled_on": "2026-08-31", "utr": "UTRDEMO0900", "gross_amount": 800000, "fees": null, "tax": null, "refunds": 0, "adjustments": 0, "net_amount": 781600}], "payments": [], "refunds": [], "failed_payments": [], "payment_links": []}
  ],
  "ui_anchors": {
    "settlement.gross_amount": "Gross amount",
    "settlement.fees": "Razorpay fees",
    "settlement.tax": "Tax on fees",
    "settlement.refunds": "Refunds",
    "settlement.adjustments": "Adjustments",
    "settlement.net_amount": "Net settlement",
    "settlement.period": "Settlement period",
    "settlement.utr": "UTR",
    "settlement.status": "Status",
    "nav.payments": "Payments",
    "nav.settlements": "Settlements",
    "nav.refunds": "Refunds",
    "nav.payment_links": "Payment Links",
    "nav.reports": "Reports",
    "payments.date_filter": "Date range",
    "payments.status_filter": "Status",
    "payments.failed_option": "Failed",
    "payments.apply_filter": "Apply filters",
    "payments.error_reason": "Failure reason",
    "payments.table": "Payment ID",
    "refunds.table": "Refund ID",
    "refunds.type": "Refund type",
    "link.amount": "Amount",
    "link.description": "Description",
    "link.expiry": "Expire by",
    "link.customer_name": "Customer name",
    "link.customer_contact": "Phone number",
    "link.preview": "Preview link",
    "link.create_button": "Create payment link",
    "reports.download": "Download report"
  }
};

let seed = null;
let currentPage = "home";
let currentScenario = null;
let filterState = { dateFrom: "", dateTo: "", status: "" };

// ===== HELPERS =====
function formatRupees(paise) {
  if (!paise && paise !== 0) return "—";
  const rupees = Math.floor(paise / 100);
  const ps = paise % 100;
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  return ps > 0 ? `₹${formatted}.${ps.toString().padStart(2, "0")}` : `₹${formatted}`;
}

function formatDate(isoStr) {
  if (!isoStr) return "—";
  const d = new Date(isoStr);
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

function formatTime(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

// ===== LOAD SEED =====
async function loadSeed() {
  try {
    const res = await fetch("/api/merchant/seed");
    if (res.ok) return await res.json();
  } catch {}
  try {
    const res = await fetch("../merchant/seed/dashboard_seed.json");
    if (res.ok) return await res.json();
  } catch {}
  return EMBEDDED_SEED;
}

// ===== CLICKY BRIDGE =====
// Publishing a wrong rect is worse than publishing none: Clicky would point
// confidently at the wrong place instead of falling back to reading the screen.
// `outerHeight - innerHeight` is only an estimate of the browser chrome, and it
// goes wrong when the page is embedded, zoomed or on a secondary monitor — it
// can produce a negative Y for an element that is plainly visible. So every
// rect is sanity-checked before it goes out.
function isPlausibleRect(x, y, w, h) {
  if (!isFinite(x) || !isFinite(y) || !isFinite(w) || !isFinite(h)) return false;
  if (w <= 0 || h <= 0) return false;
  if (w > 8000 || h > 8000) return false;
  if (x < -64 || y < -64) return false;
  if (x > 32000 || y > 32000) return false;
  return true;
}

window.__clickyScreenMap = function() {
  const map = {};
  const chromeH = Math.max(0, window.outerHeight - window.innerHeight);
  document.querySelectorAll("[data-clicky-target]").forEach(el => {
    if (el.offsetParent === null) return; // hidden
    const rect = el.getBoundingClientRect();
    const x = Math.round(window.screenX + rect.left);
    const y = Math.round(window.screenY + chromeH + rect.top);
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);
    if (!isPlausibleRect(x, y, w, h)) return; // omit rather than mislead
    map[el.getAttribute("data-clicky-target")] = [x, y, w, h];
  });
  return map;
};

window.__clickyPageId = function() {
  return currentPage;
};

function postScreenMap() {
  const map = window.__clickyScreenMap();
  const pageId = window.__clickyPageId();
  fetch("http://127.0.0.1:8756/api/merchant/screen-map", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({page: pageId, map: map, url: location.href})
  }).catch(() => {});
}

setInterval(postScreenMap, 1500);

// ===== PAGE RENDER FUNCTIONS =====
function renderHome(scenario) {
  const payments = scenario.payments || [];
  const settlements = scenario.settlements || [];
  const failedPayments = scenario.failed_payments || [];

  const todayPayments = payments.filter(p => p.created_at?.startsWith("2026-09-03"));
  const todayCollection = todayPayments.reduce((s, p) => s + p.amount, 0);

  const pendingSettlement = settlements.filter(s => s.status === "pending").reduce((s, s2) => s + (s2.net_amount || 0), 0);
  const failedCount = failedPayments.length;

  const html = `
    <h1 class="page-title">Home</h1>
    <div class="tiles-grid">
      <div class="tile">
        <div class="tile-label">Today's Collection</div>
        <div class="tile-value">${formatRupees(todayCollection)}</div>
        <div class="tile-meta">${todayPayments.length} payments</div>
      </div>
      <div class="tile">
        <div class="tile-label">Pending Settlement</div>
        <div class="tile-value">${formatRupees(pendingSettlement)}</div>
      </div>
      <div class="tile">
        <div class="tile-label">Failed Payments</div>
        <div class="tile-value">${failedCount}</div>
      </div>
    </div>
  `;
  return html;
}

function renderPayments(scenario) {
  if (scenario.simulate_error) return "";

  const payments = (scenario.payments || []).concat(scenario.failed_payments || []);
  if (payments.length === 0) {
    return `
      <h1 class="page-title">Payments</h1>
      <div class="table-container">
        <div class="empty-state">
          <div class="empty-icon">💳</div>
          <div class="empty-title">No payments yet</div>
          <div class="empty-text">Payments will appear here once you start accepting transactions.</div>
        </div>
      </div>
    `;
  }

  const filtered = payments.filter(p => {
    if (filterState.status === "failed" && p.status !== "failed") return false;
    if (filterState.dateFrom && p.created_at < filterState.dateFrom) return false;
    if (filterState.dateTo && p.created_at > filterState.dateTo + "T23:59:59") return false;
    return true;
  });

  const hasFailed = payments.some(p => p.status === "failed");
  let html = `<h1 class="page-title">Payments</h1>
    <div class="table-container">
      <div class="filter-bar">
        <div class="filter-group">
          <label data-clicky-target="payments.date_filter">Date range</label>
          <input type="date" id="dateFrom" value="${filterState.dateFrom}">
        </div>
        <div class="filter-group">
          <label data-clicky-target="payments.status_filter">Status</label>
          <select id="statusFilter">
            <option value="">All</option>
            <option value="failed" data-clicky-target="payments.failed_option">Failed</option>
          </select>
        </div>
        <div class="form-group">
          <button class="btn-primary" id="applyFilters" data-clicky-target="payments.apply_filter">Apply filters</button>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th data-clicky-target="payments.table">Payment ID</th>
            <th>Customer</th>
            <th>Amount</th>
            <th>Status</th>
            <th>Method</th>
            <th>Date</th>
            ${hasFailed ? `<th data-clicky-target="payments.error_reason">Failure reason</th>` : ""}
          </tr>
        </thead>
        <tbody>
          ${filtered.map(p => `
            <tr>
              <td>${p.id}</td>
              <td>${p.customer_name}</td>
              <td class="amount">${formatRupees(p.amount)}</td>
              <td><span class="badge ${p.status}">${p.status}</span></td>
              <td style="text-transform: capitalize;">${p.method}</td>
              <td>${formatDate(p.created_at)}</td>
              ${hasFailed ? `<td>${p.error_description || "—"}</td>` : ""}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
  return html;
}

function renderSettlements(scenario) {
  if (scenario.simulate_error) return "";

  const settlements = scenario.settlements || [];
  if (settlements.length === 0) {
    return `
      <h1 class="page-title">Settlements</h1>
      <div class="table-container">
        <div class="empty-state">
          <div class="empty-icon">🏦</div>
          <div class="empty-title">No settlements yet</div>
          <div class="empty-text">Settlements will appear here as funds are transferred to your account.</div>
        </div>
      </div>
    `;
  }

  let html = `<h1 class="page-title">Settlements</h1>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Settlement ID</th>
            <th>Period</th>
            <th>Amount</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${settlements.map(s => `
            <tr class="settlement-row" data-settlement-id="${s.id}">
              <td>${s.id}</td>
              <td>${formatDate(s.period_start)} to ${formatDate(s.period_end)}</td>
              <td class="amount">${formatRupees(s.net_amount)}</td>
              <td><span class="badge ${s.status}">${s.status}</span></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
  return html;
}

function renderRefunds(scenario) {
  if (scenario.simulate_error) return "";

  const refunds = scenario.refunds || [];
  if (refunds.length === 0) {
    return `
      <h1 class="page-title">Refunds</h1>
      <div class="table-container">
        <div class="empty-state">
          <div class="empty-icon">↩</div>
          <div class="empty-title">No refunds yet</div>
          <div class="empty-text">Refunds will appear here once you start processing refunds.</div>
        </div>
      </div>
    `;
  }

  let html = `<h1 class="page-title">Refunds</h1>
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th data-clicky-target="refunds.table">Refund ID</th>
            <th>Payment ID</th>
            <th>Amount</th>
            <th data-clicky-target="refunds.type">Refund type</th>
            <th>Status</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          ${refunds.map(r => `
            <tr>
              <td>${r.id}</td>
              <td>${r.payment_id}</td>
              <td class="amount">${formatRupees(r.amount)}</td>
              <td><span class="badge ${r.type}">${r.type === "full" ? "Full" : "Partial"}</span></td>
              <td><span class="badge ${r.status}">${r.status}</span></td>
              <td>${r.reason}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
  return html;
}

function renderPaymentLinks(scenario) {
  const links = scenario.payment_links || [];
  let html = `<h1 class="page-title">Payment Links</h1>
    <div class="banner">Demo only — no real payment link is ever created or sent.</div>
    <div class="link-form">
      <h3 style="margin-bottom: 16px; color: #0c2451;">Create Payment Link</h3>
      <div class="form-group">
        <label for="linkAmount" data-clicky-target="link.amount">Amount</label>
        <input type="number" id="linkAmount" placeholder="0" min="0">
      </div>
      <div class="form-group">
        <label for="linkDesc" data-clicky-target="link.description">Description</label>
        <textarea id="linkDesc" placeholder="What is this payment for?"></textarea>
      </div>
      <div class="form-group">
        <label for="linkExpiry" data-clicky-target="link.expiry">Expire by</label>
        <input type="datetime-local" id="linkExpiry">
      </div>
      <div class="form-group">
        <label for="linkCustName" data-clicky-target="link.customer_name">Customer name</label>
        <input type="text" id="linkCustName" placeholder="Name">
      </div>
      <div class="form-group">
        <label for="linkCustPhone" data-clicky-target="link.customer_contact">Phone number</label>
        <input type="tel" id="linkCustPhone" placeholder="+91...">
      </div>
      <div class="form-actions">
        <button class="btn-secondary" id="previewLink" data-clicky-target="link.preview">Preview link</button>
        <button class="btn-primary" id="createLink" data-clicky-target="link.create_button">Create payment link</button>
      </div>
    </div>
  `;

  if (links.length > 0) {
    html += `<h3 style="margin-bottom: 16px; color: #0c2451;">Existing Links</h3>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Link ID</th>
              <th>Description</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Customer</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
            ${links.map(l => `
              <tr>
                <td>${l.id}</td>
                <td>${l.description}</td>
                <td class="amount">${formatRupees(l.amount)}</td>
                <td><span class="badge ${l.status}">${l.status}</span></td>
                <td>${l.customer_name}</td>
                <td><a href="${l.short_url}" target="_blank" style="color: #3395ff; text-decoration: none;">View</a></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
  }
  return html;
}

function renderReports(scenario) {
  return `
    <h1 class="page-title">Reports</h1>
    <div class="table-container" style="padding: 20px;">
      <p style="margin-bottom: 16px;">Download a CSV report of all transactions.</p>
      <button class="btn-primary" id="downloadReport" data-clicky-target="reports.download">Download report</button>
    </div>
  `;
}

// ===== RENDER PAGE =====
function renderPage(pageId) {
  currentPage = pageId;
  document.querySelector("meta[name='clicky-page']").setAttribute("content", pageId);

  // Keep the nav highlight in step with what is actually rendered. Doing this
  // here — rather than in each click handler — means the sidebar can never
  // disagree with the page, including on first load and on scenario switches,
  // where it previously always said "Home".
  document.querySelectorAll(".nav-item").forEach(item => {
    const isActive = item.getAttribute("data-page") === pageId;
    item.classList.toggle("active", isActive);
    const btn = item.querySelector(".nav-button");
    if (btn) btn.setAttribute("aria-current", isActive ? "page" : "false");
  });

  const scenario = currentScenario || seed.scenarios.find(s => s.default);
  const errorCard = document.getElementById("error-card");
  const container = document.getElementById("page-container");

  // Clear
  container.innerHTML = "";
  errorCard.style.display = "none";

  // Error state?
  if (scenario.simulate_error) {
    errorCard.style.display = "flex";
    document.getElementById("error-title").textContent = scenario.simulate_error.code || "Error";
    document.getElementById("error-message").textContent = scenario.simulate_error.message || "Unable to load data.";
    return;
  }

  let html = "";
  switch (pageId) {
    case "home": html = renderHome(scenario); break;
    case "payments": html = renderPayments(scenario); break;
    case "settlements": html = renderSettlements(scenario); break;
    case "refunds": html = renderRefunds(scenario); break;
    case "payment_links": html = renderPaymentLinks(scenario); break;
    case "reports": html = renderReports(scenario); break;
  }

  container.innerHTML = html;

  // Attach event listeners
  if (pageId === "payments") {
    document.getElementById("applyFilters")?.addEventListener("click", () => {
      filterState.dateFrom = document.getElementById("dateFrom").value;
      filterState.status = document.getElementById("statusFilter").value;
      renderPage("payments");
      postScreenMap();
    });
  }

  if (pageId === "settlements") {
    document.querySelectorAll(".settlement-row").forEach(row => {
      row.addEventListener("click", () => showSettlementModal(row.getAttribute("data-settlement-id"), scenario));
    });
  }

  if (pageId === "payment_links") {
    document.getElementById("createLink")?.addEventListener("click", (e) => {
      e.preventDefault();
      showLinkModal();
    });
    document.getElementById("previewLink")?.addEventListener("click", (e) => {
      e.preventDefault();
      showLinkModal();
    });
  }

  if (pageId === "reports") {
    document.getElementById("downloadReport")?.addEventListener("click", () => downloadReport(scenario));
  }

  postScreenMap();
}

// ===== SETTLEMENT MODAL =====
function showSettlementModal(settlementId, scenario) {
  const settlement = scenario.settlements.find(s => s.id === settlementId);
  if (!settlement) return;

  const anchors = seed.ui_anchors;
  let html = `
    <div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.period">${anchors["settlement.period"]}</div>
      <div class="detail-value">${formatDate(settlement.period_start)} to ${formatDate(settlement.period_end)}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.status">${anchors["settlement.status"]}</div>
      <div class="detail-value"><span class="badge ${settlement.status}">${settlement.status}</span></div>
    </div>
    <div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.gross_amount">${anchors["settlement.gross_amount"]}</div>
      <div class="detail-value">${formatRupees(settlement.gross_amount)}</div>
    </div>
  `;

  if (settlement.fees === null) {
    html += `<div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.fees">${anchors["settlement.fees"]}</div>
      <div class="detail-value"><span class="detail-unavailable">not available</span></div>
    </div>`;
  } else {
    html += `<div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.fees">${anchors["settlement.fees"]}</div>
      <div class="detail-value">${formatRupees(settlement.fees)}</div>
    </div>`;
  }

  if (settlement.tax === null) {
    html += `<div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.tax">${anchors["settlement.tax"]}</div>
      <div class="detail-value"><span class="detail-unavailable">not available</span></div>
    </div>`;
  } else {
    html += `<div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.tax">${anchors["settlement.tax"]}</div>
      <div class="detail-value">${formatRupees(settlement.tax)}</div>
    </div>`;
  }

  html += `
    <div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.refunds">${anchors["settlement.refunds"]}</div>
      <div class="detail-value">${settlement.refunds > 0 ? formatRupees(settlement.refunds) : "—"}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label" data-clicky-target="settlement.adjustments">${anchors["settlement.adjustments"]}</div>
      <div class="detail-value">${settlement.adjustments !== 0 ? formatRupees(settlement.adjustments) : "—"}</div>
    </div>
    <div class="detail-row" style="border-bottom: none; font-weight: 700;">
      <div class="detail-label" data-clicky-target="settlement.net_amount">${anchors["settlement.net_amount"]}</div>
      <div class="detail-value">${formatRupees(settlement.net_amount)}</div>
    </div>
  `;

  if (settlement.utr) {
    html += `<div class="detail-row" style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #f0f1f3;">
      <div class="detail-label" data-clicky-target="settlement.utr">${anchors["settlement.utr"]}</div>
      <div class="detail-value">${settlement.utr}</div>
    </div>`;
  }

  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("settlement-modal").style.display = "flex";
  postScreenMap();
}

// ===== LINK MODAL =====
function showLinkModal() {
  document.getElementById("link-modal").style.display = "flex";
  postScreenMap();
}

// ===== DOWNLOAD REPORT =====
function downloadReport(scenario) {
  const payments = (scenario.payments || []).concat(scenario.failed_payments || []);
  const refunds = scenario.refunds || [];

  let csv = "Type,ID,Amount (INR),Status,Customer,Date,Description\n";
  payments.forEach(p => {
    const amt = (p.amount / 100).toFixed(2);
    csv += `Payment,${p.id},${amt},${p.status},${p.customer_name},"${formatDate(p.created_at)}","${p.description}"\n`;
  });
  refunds.forEach(r => {
    const amt = (r.amount / 100).toFixed(2);
    csv += `Refund,${r.id},${amt},${r.status},,,"${r.reason}"\n`;
  });

  const blob = new Blob([csv], {type: "text/csv"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report_${seed.today}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ===== INIT =====
document.addEventListener("DOMContentLoaded", async () => {
  seed = await loadSeed();

  // Scenario select
  const select = document.getElementById("scenario-select");
  seed.scenarios.forEach((s, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = s.title;
    if (s.default) opt.selected = true;
    select.appendChild(opt);
  });
  select.addEventListener("change", () => {
    currentScenario = seed.scenarios[parseInt(select.value)];
    filterState = {dateFrom: "", dateTo: "", status: ""};
    renderPage(currentScenario.page || "home");
  });

  // Nav buttons
  document.querySelectorAll(".nav-button").forEach(btn => {
    btn.addEventListener("click", () => {
      const pageId = btn.closest(".nav-item").getAttribute("data-page");
      renderPage(pageId);  // renderPage syncs the nav highlight itself
    });
  });

  // Modal close buttons
  document.querySelectorAll(".modal-close").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.closest(".modal").style.display = "none";
      postScreenMap();
    });
  });
  document.querySelectorAll(".modal-overlay").forEach(overlay => {
    overlay.addEventListener("click", (e) => {
      e.target.closest(".modal").style.display = "none";
      postScreenMap();
    });
  });

  // Initial render
  currentScenario = seed.scenarios.find(s => s.default);
  renderPage(currentScenario.page || "home");
});
