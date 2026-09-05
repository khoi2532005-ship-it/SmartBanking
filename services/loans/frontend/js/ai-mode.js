function explain(kind) {
    const loanId = document.getElementById("ai_loan_id").value;
    show("explanation-result", "<p>Thinking...</p>");
    api(`/api/ai/loans/${loanId}/${kind}`)
        .then((result) => result.ok
            ? show("explanation-result", `<pre>${result.body.explanation}</pre>`)
            : show("explanation-result", `<p>Error: ${result.body.error || result.status}</p>`))
        .catch((error) => show("explanation-result", errorBox(error)));
}

// AI Explanations for a loan
document.getElementById("explain-eligibility-btn").addEventListener("click", () => explain("explain-eligibility"));
document.getElementById("explain-decision-btn").addEventListener("click", () => explain("explain-decision"));
document.getElementById("explain-repayments-btn").addEventListener("click", () => explain("explain-repayments"));

// Compare repayment options
document.getElementById("compare-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {};
    if (document.getElementById("cmp_loan_id").value) payload.loan_id = document.getElementById("cmp_loan_id").value;
    if (document.getElementById("cmp_amount").value) payload.amount = document.getElementById("cmp_amount").value;
    if (document.getElementById("cmp_rate").value) payload.interest_rate = document.getElementById("cmp_rate").value;
    if (document.getElementById("cmp_income").value) payload.monthly_income = document.getElementById("cmp_income").value;
    if (document.getElementById("cmp_terms").value) {
        payload.terms = document.getElementById("cmp_terms").value.split(",").map((t) => t.trim()).filter(Boolean);
    }

    show("compare-result", "<p>Comparing options...</p>");
    try {
        const result = await api("/api/ai/repayment-options", { method: "POST", body: JSON.stringify(payload) });
        if (!result.ok) return show("compare-result", `<p>Error: ${result.body.error || result.status}</p>`);
        const rows = result.body.options.map((o) => `
            <tr><td>${o.term_months} mo</td><td>$${Number(o.monthly_payment).toFixed(2)}</td>
            <td>$${Number(o.total_interest).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
            <td>${o.payment_share_of_income != null ? o.payment_share_of_income + "%" : "-"}</td></tr>`).join("");
        show("compare-result",
            `<table><tr><th>Term</th><th>Monthly</th><th>Total Interest</th><th>% of Income</th></tr>${rows}</table>
             <p><b>AI Recommendation:</b></p><pre>${result.body.recommendation}</pre>`);
    } catch (error) { show("compare-result", errorBox(error)); }
});
