// MCP Mode for Loans & Credit - Release 1 integration.
// Mirrors the enrolment-app MCP tab: an on/off toggle persisted in
// localStorage plus a tool form that POSTs to the loans backend, which runs
// the tool against the shared MCP server. The X-MCP-Mode header is the same
// per-request gate the backend checks alongside MCP_ENABLED.
const MCP_BASE = `http://${window.location.hostname}:5002`;
const MCP_STORAGE_KEY = "loans_mcp_mode_enabled";

const mcpToggle = document.getElementById("mcp-mode-toggle");
const mcpState = document.getElementById("mcp-mode-state");
const mcpResult = document.getElementById("mcp-result");

function mcpEnabled() {
    return mcpToggle.checked;
}

function renderMcpState() {
    const on = mcpEnabled();
    mcpState.textContent = on ? "ON" : "OFF";
    mcpState.classList.toggle("feature-on", on);
    mcpState.classList.toggle("feature-off", !on);
}

function saveMcpMode() {
    localStorage.setItem(MCP_STORAGE_KEY, String(mcpEnabled()));
}

function loadMcpMode() {
    const persisted = localStorage.getItem(MCP_STORAGE_KEY);
    mcpToggle.checked = persisted === null ? true : persisted === "true";
    renderMcpState();
}

function escMcp(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function showMcpError(message) {
    mcpResult.innerHTML = `<p class="alert alert-error">${escMcp(message)}</p>`;
}

function renderMcpDisabled() {
    showMcpError("MCP Mode is OFF. Enable MCP Mode to run MCP tools.");
}

async function callMcp(path, body) {
    const response = await fetch(`${MCP_BASE}${path}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-MCP-Mode": mcpEnabled() ? "on" : "off",
        },
        body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
}

function loansResultTable(result) {
    const loans = Array.isArray(result.loans) ? result.loans : [];
    if (!loans.length) return "<p class='empty'>No loans found for this customer.</p>";
    const rows = loans.map((loan) => `
        <tr>
            <td>${escMcp(loan.loan_id)}</td>
            <td>${escMcp(loan.loan_type)}</td>
            <td class="num">$${Number(loan.requested_amount || 0).toLocaleString()}</td>
            <td>${escMcp(loan.status)}</td>
        </tr>`).join("");
    return `<table><tr><th>Loan ID</th><th>Type</th><th>Requested</th><th>Status</th></tr>${rows}</table>`;
}

document.getElementById("mcp-loans-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!mcpEnabled()) {
        renderMcpDisabled();
        return;
    }

    const payload = { customer_id: document.getElementById("mcp_customer_id").value };
    const status = document.getElementById("mcp_status").value;
    if (status) payload.status = status;

    mcpResult.classList.remove("is-hidden");
    mcpResult.innerHTML = "<p class='spinner'>Running MCP loans_list&hellip;</p>";

    try {
        const result = await callMcp("/api/mcp/loans-list", payload);
        if (!result.ok) {
            showMcpError(result.data.error || `Request failed (${result.status}).`);
            return;
        }
        const r = result.data.result || {};
        const source = r.source || {};
        mcpResult.innerHTML = `
            <h3>MCP Tool: loans_list</h3>
            ${loansResultTable(r)}
            <p class="muted">${escMcp(r.loan_count ?? 0)} loans for customer ${escMcp(r.customer_id)}
                ${r.status_filter ? `filtered by status ${escMcp(r.status_filter)}` : ""}
                &middot; source: ${escMcp(source.feature || "loans")} ${escMcp(source.endpoint || "")}</p>`;
    } catch (error) {
        showMcpError(error && error.message ? error.message : String(error));
    }
});

mcpToggle.addEventListener("change", () => {
    saveMcpMode();
    renderMcpState();
    if (!mcpEnabled()) renderMcpDisabled();
});

loadMcpMode();
if (!mcpEnabled()) renderMcpDisabled();