const API = "http://localhost:5002";

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

function loansTable(loans) {
    if (!Array.isArray(loans) || !loans.length) return "<p>No loan applications found.</p>";
    const rows = loans.map((l) => `
        <tr>
            <td>${l.loan_id}</td><td>${l.customer_id}</td><td>${l.loan_type}</td>
            <td>$${Number(l.requested_amount).toLocaleString()}</td>
            <td>${l.status}</td><td>${l.interest_rate ?? "-"}</td>
            <td>${l.approved_amount ? "$" + Number(l.approved_amount).toLocaleString() : "-"}</td>
            <td>${String(l.application_date).slice(0, 10)}</td>
        </tr>`).join("");
    return `<table><tr><th>ID</th><th>Customer</th><th>Type</th><th>Requested</th>
        <th>Status</th><th>Rate %</th><th>Approved</th><th>Date</th></tr>${rows}</table>`;
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
        } else show("apply-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("apply-result", errorBox(error)); }
});

// Search loans
document.getElementById("search-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const params = new URLSearchParams();
    if (document.getElementById("q").value) params.set("q", document.getElementById("q").value);
    if (document.getElementById("f_status").value) params.set("status", document.getElementById("f_status").value);
    if (document.getElementById("f_loan_type").value) params.set("loan_type", document.getElementById("f_loan_type").value);
    try {
        const result = await api(`/api/loans?${params}`);
        result.ok ? show("loans-result", loansTable(result.body))
                  : show("loans-result", `<p>Error: ${result.body.error || result.status}</p>`);
    } catch (error) { show("loans-result", errorBox(error)); }
});

// View loan details and manage decisions
const detailIdInput = document.getElementById("detail_id");

async function viewDetails() {
    try {
        const result = await api(`/api/loans/${detailIdInput.value}`);
        if (!result.ok) return show("detail-result", `<p>Error: ${result.body.error || result.status}</p>`);
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
