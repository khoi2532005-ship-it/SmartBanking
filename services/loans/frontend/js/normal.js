const API = `http://${window.location.hostname}:5002`;

async function api(path, options = {}) {
    options.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    const response = await fetch(`${API}${path}`, options);
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, body };
}

function show(panelId, content) {
    const panel = document.getElementById(panelId);
    panel.classList.remove("is-hidden");
    panel.innerHTML = content;
}

function errorBox(error) {
    return `<p>Request failed.</p><pre>${errorMessage(error)}</pre>`;
}

function errorMessage(error, status = "") {
    if (typeof error === "string") return error;
    if (error && typeof error.message === "string") return error.message;
    if (error && typeof error.error === "string") return error.error;
    return status ? `Request failed (${status}).` : "Request failed.";
}

function repaymentsTable(repayments) {
    if (!Array.isArray(repayments) || !repayments.length) return "<p>No repayments found.</p>";
    const rows = repayments.map((r) => `
        <tr>
            <td>${r.repayment_id}</td><td>${r.loan_id}</td>
            <td>${String(r.due_date).slice(0, 10)}</td>
            <td>$${Number(r.payment_amount).toFixed(2)}</td>
            <td>$${Number(r.principal_amount).toFixed(2)}</td>
            <td>$${Number(r.interest_amount).toFixed(2)}</td>
            <td>$${Number(r.amount_paid).toFixed(2)}</td>
            <td>${r.payment_status}</td>
        </tr>`).join("");
    return `<table><tr><th>ID</th><th>Loan</th><th>Due</th><th>Payment</th><th>Principal</th>
        <th>Interest</th><th>Paid</th><th>Status</th></tr>${rows}</table>`;
}

// Submit application
document.getElementById("apply-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const payload = {};
    ["customer_id", "requested_amount", "term_months", "monthly_income", "loan_purpose"].forEach((name) => {
        if (form.elements[name].value !== "") payload[name] = form.elements[name].value;
    });
    payload.loan_type = form.elements.loan_type.value;
    try {
        const result = await api("/api/loans", { method: "POST", body: JSON.stringify(payload) });
        if (result.ok) {
            const e = result.body.eligibility;
            show("apply-result",
                `<p><b>Application #${result.body.loan.loan_id} submitted (PENDING).</b><br>
                 Eligible now: ${e.eligible ? "Yes" : "No"} |
                 Est. payment: $${e.estimated_monthly_payment ?? "-"} @ ${e.proposed_interest_rate ?? "-"}%</p>
                 <ul>${e.checks.map((c) => `<li>${c.passed ? "PASS" : "FAIL"} - ${c.detail}</li>`).join("")}</ul>`);
            loadLoans();
        } else show("apply-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("apply-result", errorBox(error)); }
});

// Loan applications list: loads on open and follows the search box; the type
// select and the status tabs filter it here, and the tiles cover every loan.
let allLoans = [];
let loans = [];              // matching the search box
let loansRequest = 0;        // only the newest request may render
let loansReady = false;

const LOAN_PILLS = { PENDING: "pill-warn", APPROVED: "pill-ok", REJECTED: "pill-over", CANCELLED: "pill-neutral" };
const loanStatus = (l) => String(l.status || "").toUpperCase();
// Seeded loans say "Personal Loan" and new ones "PERSONAL", so match the start.
const typeMatches = (l, type) => !type || String(l.loan_type || "").toUpperCase().startsWith(type);

function renderLoanTiles() {
    const count = (status) => allLoans.filter((l) => loanStatus(l) === status).length;
    const approved = allLoans.filter((l) => loanStatus(l) === "APPROVED");
    const approvedTotal = approved.reduce((sum, l) => sum + (Number(l.approved_amount) || 0), 0);
    const requestedTotal = allLoans.reduce((sum, l) => sum + (Number(l.requested_amount) || 0), 0);
    SB.renderTiles(document.getElementById("loan-tiles"), [
        { label: "Applications", value: allLoans.length, sub: `${count("PENDING")} pending review` },
        { label: "Approved amount", value: SB.fmtMoneyShort(approvedTotal), sub: SB.plural(approved.length, "approved loan") },
        { label: "Requested", value: SB.fmtMoneyShort(requestedTotal),
          sub: allLoans.length ? `average ${SB.fmtMoneyShort(requestedTotal / allLoans.length)}` : "no applications yet" },
        { label: "Rejected", value: count("REJECTED"), sub: `${count("CANCELLED")} cancelled` },
    ]);
}

const loanTabs = SB.tabs(document.getElementById("loan-status-tabs"), () => renderLoans());
const loanSort = SB.sortable(document.querySelector("#loans-wrap thead"),
    { key: "application_date", dir: "desc" }, () => renderLoans(),
    { requested_amount: "desc", approved_amount: "desc", interest_rate: "desc", application_date: "desc" });

function renderLoans() {
    if (!loansReady) return;
    const ofType = loans.filter((l) => typeMatches(l, document.getElementById("f_loan_type").value));
    loanTabs.update(SB.countBy(ofType, loanStatus));
    const visible = loanTabs.value ? ofType.filter((l) => loanStatus(l) === loanTabs.value) : ofType;
    const valueOf = {
        loan_id: (l) => Number(l.loan_id),
        customer_id: (l) => Number(l.customer_id),
        loan_type: (l) => String(l.loan_type),
        requested_amount: (l) => Number(l.requested_amount) || 0,
        approved_amount: (l) => Number(l.approved_amount) || 0,
        interest_rate: (l) => Number(l.interest_rate) || 0,
        application_date: (l) => String(l.application_date || ""),
        status: (l) => loanStatus(l),
    }[loanSort.key];
    const rows = SB.sortBy(visible, valueOf, loanSort.dir);
    document.getElementById("loans-body").innerHTML = rows.length ? rows.map((l) => `
        <tr class="is-clickable" data-loan="${Number(l.loan_id)}">
            <td><button type="button" class="link-btn">#${SB.esc(l.loan_id)}</button></td>
            <td>#${SB.esc(l.customer_id)}</td>
            <td>${SB.esc(SB.titleCase(l.loan_type))}${l.loan_purpose ? `<span class="cell-sub">${SB.esc(l.loan_purpose)}</span>` : ""}</td>
            <td class="num">${SB.esc(SB.fmtMoney(l.requested_amount))}</td>
            <td class="num">${l.approved_amount ? SB.esc(SB.fmtMoney(l.approved_amount)) : "–"}</td>
            <td class="num">${l.interest_rate != null ? `${SB.esc(l.interest_rate)}%` : "–"}</td>
            <td class="nowrap">${SB.esc(String(l.application_date || "").slice(0, 10))}</td>
            <td><span class="pill ${LOAN_PILLS[loanStatus(l)] || "pill-neutral"}">${SB.esc(SB.titleCase(l.status))}</span></td>
        </tr>`).join("")
        : '<tr class="empty-row"><td colspan="8"><div class="empty-state"><strong>No loan applications match these filters</strong></div></td></tr>';
    document.getElementById("loans-count").textContent = `Showing ${rows.length} of ${SB.plural(loans.length, "application")}`;
}

async function loadLoans() {
    const request = ++loansRequest;
    const q = document.getElementById("q").value.trim();
    const wrap = document.getElementById("loans-wrap");
    wrap.classList.add("is-loading");
    try {
        const [matching, all] = await Promise.all([
            api(`/api/loans${q ? `?q=${encodeURIComponent(q)}` : ""}`),
            q ? api("/api/loans") : null,
        ]);
        if (request !== loansRequest) return;
        if (!matching.ok) {
            document.getElementById("loans-body").innerHTML = `<tr class="empty-row"><td colspan="8">
                <p class="alert alert-error">Error: ${SB.esc(matching.body.error || matching.status)}</p></td></tr>`;
            return;
        }
        loans = Array.isArray(matching.body) ? matching.body : [];
        if (!all) allLoans = loans;
        else if (all.ok && Array.isArray(all.body)) allLoans = all.body;
        loansReady = true;
        renderLoanTiles();
        renderLoans();
    } catch (error) {
        if (request === loansRequest) {
            document.getElementById("loans-body").innerHTML = `<tr class="empty-row"><td colspan="8">
                <p class="alert alert-error">Request failed - is loan-service running? (${SB.esc(error.message || error)})</p></td></tr>`;
        }
    } finally {
        if (request === loansRequest) wrap.classList.remove("is-loading");
    }
}

document.getElementById("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    loadLoans();
});
document.getElementById("q").addEventListener("input", SB.debounce(() => loadLoans()));
document.getElementById("f_loan_type").addEventListener("change", () => renderLoans());

// Selecting an application opens its details below and sets it for AI Mode.
document.getElementById("loans-body").addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-loan]");
    if (!row) return;
    detailIdInput.value = row.dataset.loan;
    document.getElementById("ai_loan_id").value = row.dataset.loan;
    viewDetails();
    document.getElementById("detail-form").closest(".card").scrollIntoView({ behavior: "smooth", block: "start" });
});

// View loan details and manage decisions
const detailIdInput = document.getElementById("detail_id");
const decisionButtons = ["approve-btn", "reject-btn", "delete-btn"]
    .map((id) => document.getElementById(id));

function showDecisionButtons() {
    decisionButtons.forEach((button) => {
        button.hidden = false;
        button.classList.remove("is-hidden");
    });
}

async function viewDetails() {
    try {
        const result = await api(`/api/loans/${detailIdInput.value}`);
        if (!result.ok) return show("detail-result", `<p>Error: ${result.body.error || result.status}</p>`);
        showDecisionButtons();
        const l = result.body;
        show("detail-result",
            `<p><b>Loan #${l.loan_id}</b> - ${l.loan_type} - <b>${l.status}</b><br>
             Customer ${l.customer_id} | Requested $${Number(l.requested_amount).toLocaleString()} |
             Approved ${l.approved_amount ? "$" + Number(l.approved_amount).toLocaleString() : "-"} |
             Rate ${l.interest_rate ?? "-"}% | Term ${l.term_months ?? "-"} months<br>
             Purpose: ${l.loan_purpose} | Applied: ${String(l.application_date).slice(0, 10)}</p>
             ${repaymentsTable(l.repayments)}`);
    } catch (error) { show("detail-result", errorBox(error)); }
}

document.getElementById("detail-form").addEventListener("submit", (e) => { e.preventDefault(); viewDetails(); });

async function decision(action) {
    try {
        const result = await api(`/api/loans/${detailIdInput.value}/decision`, {
            method: "POST", body: JSON.stringify({ action }),
        });
        if (result.ok) {
            show("detail-result",
                `<p><b>${action === "APPROVE" ? "Approved" : "Rejected"}.</b> ` +
                (action === "APPROVE"
                    ? `${result.body.repayments_created} repayments created, first due ${result.body.first_due_date}, monthly $${result.body.monthly_payment}.`
                    : "") + "</p>");
            viewDetails();
            loadLoans();
        } else show("detail-result", `<p>Error: ${errorMessage(result.body, result.status)}</p>`);
    } catch (error) { show("detail-result", errorBox(error)); }
}

document.getElementById("eligibility-btn").addEventListener("click", async () => {
    try {
        const result = await api(`/api/loans/${detailIdInput.value}/eligibility`);
        const e = result.body.eligibility;
        result.ok ? show("detail-result",
            `<p><b>Eligible: ${e.eligible ? "Yes" : "No"}</b> | Rate ${e.proposed_interest_rate ?? "-"}% |
             Term ${e.proposed_term_months ?? "-"} mo | Payment $${e.estimated_monthly_payment ?? "-"}</p>
             <ul>${e.checks.map((c) => `<li>${c.passed ? "PASS" : "FAIL"} - ${c.detail}</li>`).join("")}</ul>`)
                  : show("detail-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("detail-result", errorBox(error)); }
});
document.getElementById("approve-btn").addEventListener("click", () => decision("APPROVE"));
document.getElementById("reject-btn").addEventListener("click", () => decision("REJECT"));

document.getElementById("delete-btn").addEventListener("click", async () => {
    try {
        const result = await api(`/api/loans/${detailIdInput.value}`, { method: "DELETE" });
        result.ok ? show("detail-result", `<p>Deleted loan ${detailIdInput.value} and its repayments.</p>`)
                  : show("detail-result", `<p>Error: ${result.body.error || result.status}</p>`);
        if (result.ok) loadLoans();
    } catch (error) { show("detail-result", errorBox(error)); }
});

// Repayment management
document.getElementById("repay-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    if (document.getElementById("amount_paid").value !== "")
        payload.amount_paid = document.getElementById("amount_paid").value;
    if (document.getElementById("payment_status").value)
        payload.payment_status = document.getElementById("payment_status").value;
    try {
        const result = await api(`/api/repayments/${document.getElementById("repay_id").value}`, {
            method: "PUT", body: JSON.stringify(payload),
        });
        if (result.ok) {
            const r = result.body;
            show("repay-result",
                `<p>Updated repayment #${r.repayment_id}: paid $${Number(r.amount_paid).toFixed(2)}
                 of $${Number(r.payment_amount).toFixed(2)} - <b>${r.payment_status}</b></p>`);
        } else show("repay-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("repay-result", errorBox(error)); }
});

// Repayment table views
document.getElementById("all-repayments-btn").addEventListener("click", async () => {
    try {
        const result = await api("/api/repayments");
        result.ok ? show("repayments-result", repaymentsTable(result.body))
                  : show("repayments-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("repayments-result", errorBox(error)); }
});

document.getElementById("upcoming-btn").addEventListener("click", async () => {
    try {
        const result = await api("/api/repayments/upcoming?days=30");
        result.ok ? show("repayments-result", repaymentsTable(result.body))
                  : show("repayments-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("repayments-result", errorBox(error)); }
});

loadLoans();
