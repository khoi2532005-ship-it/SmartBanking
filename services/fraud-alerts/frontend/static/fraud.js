// Fraud Alerts - helpers shared by the Normal and AI Mode tabs.

const API = `http://${window.location.hostname}:5003`;

const SEVERITIES = ["high", "medium", "low"];
// Workflow order: new -> reviewed -> confirmed fraud or dismissed.
const STATUSES = ["new", "reviewed", "confirmed", "dismissed"];
const STATUS_LABELS = { new: "New", reviewed: "Reviewed", confirmed: "Confirmed fraud", dismissed: "Dismissed" };

const RULE_TYPES = {
    amount_over: {
        label: "Large amount",
        help: "Flags any single transaction above the amount.",
    },
    velocity: {
        label: "Rapid transactions",
        help: "Flags a customer making more than the set number of transactions within the time window.",
    },
    unusual_time: {
        label: "Unusual time of day",
        help: "Flags transactions made between two hours. The end hour is not included, and the window can run past midnight.",
    },
    new_recipient_high_value: {
        label: "New recipient, high value",
        help: "Flags the first payment to a recipient the customer has never paid before, when it is above the amount.",
    },
};

const byId = (id) => document.getElementById(id);

async function api(path, options = {}) {
    options.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    const response = await fetch(`${API}${path}`, options);
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, body };
}

// Every value from the API goes through esc() before it reaches innerHTML:
// rule names and recipients are user input and explanations are model
// output, so any of them can carry markup.
function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Model output keeps its paragraphs and **bold**. It is escaped first, so the
// only markup that can appear is what this function adds.
function prose(text) {
    return esc(text).trim().split(/\n\s*\n/).map((paragraph) => `<p>${paragraph
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>")}</p>`).join("");
}

function titleCase(text) {
    const value = String(text ?? "");
    return value.charAt(0).toUpperCase() + value.slice(1);
}

// ----------------------------------------------------------------- numbers

const money = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });
const wholeMoney = new Intl.NumberFormat("en-AU", {
    style: "currency", currency: "AUD", minimumFractionDigits: 0, maximumFractionDigits: 0 });
const compactMoney = new Intl.NumberFormat("en-AU", {
    style: "currency", currency: "AUD", notation: "compact", maximumFractionDigits: 1 });

function fmtMoney(value) {
    const amount = Number(value);
    return Number.isFinite(amount) ? money.format(amount) : "–";
}

// Rule thresholds: $5,000 rather than $5,000.00, cents only when there are some.
function fmtThreshold(value) {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return "–";
    return Number.isInteger(amount) ? wholeMoney.format(amount) : money.format(amount);
}

// Headline tiles: $64.8K past ten thousand.
function fmtMoneyShort(value) {
    const amount = Number(value);
    return Number.isFinite(amount) && Math.abs(amount) >= 10000 ? compactMoney.format(amount) : fmtThreshold(amount);
}

function plural(count, word) {
    return `${count} ${word}${Number(count) === 1 ? "" : "s"}`;
}

// ------------------------------------------------------------------- dates

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Transaction times are stored as wall-clock text ("2026-08-30T12:00:00", or a
// bare date from the live Transactions API) and are shown as written: new Date()
// would read a bare date as UTC midnight and show the day before west of UTC.
// Times with an offset (explanation_generated_at is UTC) are shown in local time.
function dateParts(value) {
    const text = String(value ?? "").trim();
    if (/(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(text)) {
        const when = new Date(text);
        if (!Number.isNaN(when.getTime())) {
            return {
                date: `${when.getDate()} ${MONTHS[when.getMonth()]} ${when.getFullYear()}`,
                time: `${String(when.getHours()).padStart(2, "0")}:${String(when.getMinutes()).padStart(2, "0")}`,
            };
        }
    }
    const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(text);
    if (!match) return { date: text || "–", time: "" };
    const [, year, month, day, hour, minute] = match;
    return { date: `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`, time: hour ? `${hour}:${minute}` : "" };
}

function fmtDate(value) {
    const { date, time } = dateParts(value);
    return time ? `${date}, ${time}` : date;
}

// ------------------------------------------------------------------- rules

function hourLabel(hour) {
    return `${String(Number(hour)).padStart(2, "0")}:00`;
}

function ruleTypeLabel(type) {
    return (RULE_TYPES[type] || {}).label || type;
}

// One plain-English line for what a rule flags, matching rule_engine.py.
function describeRule(rule) {
    const value = Number(rule.threshold_value);
    const secondary = rule.threshold_secondary == null || rule.threshold_secondary === ""
        ? null : Number(rule.threshold_secondary);
    switch (rule.rule_type) {
        case "amount_over":
            return `Any transaction over ${fmtThreshold(value)}`;
        case "velocity":
            return `More than ${value} transactions within ${plural(secondary, "minute")}`;
        case "unusual_time": {
            const end = secondary ?? 24;
            return `Transactions between ${hourLabel(value)} and ${hourLabel(end)}${value > end ? " (overnight)" : ""}`;
        }
        case "new_recipient_high_value":
            return `First payment to a new recipient over ${fmtThreshold(value)}`;
        default:
            return `${rule.rule_type} ${value}${secondary != null ? ` / ${secondary}` : ""}`;
    }
}

function isEnabled(rule) {
    // A stored "false" is a truthy string; only 1/true count, as in rule_engine.py.
    return ["1", "true"].includes(String(rule.enabled).trim().toLowerCase());
}

// ------------------------------------------------------------------ badges

const SEVERITY_PILLS = { high: "pill-over", medium: "pill-warn", low: "pill-neutral" };

function severityBadge(severity) {
    return `<span class="pill pill-dot ${SEVERITY_PILLS[severity] || "pill-neutral"}">${esc(severity)}</span>`;
}

function statusBadge(status) {
    const known = STATUSES.includes(status) ? ` status-${status}` : "";
    return `<span class="status${known}">${esc(STATUS_LABELS[status] || status)}</span>`;
}

// --------------------------------------------------------------- feedback

function errorMessage(result) {
    return result.body.error || `HTTP ${result.status}`;
}

function alertBox(kind, html) {
    return `<p class="alert alert-${kind}">${html}</p>`;
}

function networkError(error) {
    return alertBox("error", `Request failed - is fraud-service running? (${esc(error.message || error)})`);
}

// Disables the button and shows a spinner while task runs. A second call for
// a button that is already busy (e.g. an example chip clicked mid-request) is
// ignored: it would save the busy label as the one to restore.
async function withBusy(button, label, task) {
    if (button.classList.contains("is-busy")) return undefined;
    const original = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-busy");
    button.textContent = label;
    try {
        return await task();
    } finally {
        button.disabled = false;
        button.classList.remove("is-busy");
        button.innerHTML = original;
    }
}

let toastTimer;

function toast(message) {
    let el = byId("toast");
    if (!el) {
        el = document.createElement("div");
        el.id = "toast";
        el.className = "toast";
        el.setAttribute("role", "status");
        document.body.append(el);
    }
    el.textContent = message;
    el.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("is-visible"), 2600);
}

// The status line in the top bar; a banner when fraud-service is down, so
// every section does not have to explain the same failure.
async function checkService({ integrations = false } = {}) {
    const status = byId("service-status");
    const item = (ok, text) => `<span class="svc"><span class="dot ${ok ? "dot-ok" : ""}"></span>${text}</span>`;
    try {
        const health = (await api("/api/health")).body || {};
        const parts = [item(true, "fraud-service online")];
        if (integrations) {
            const mcp = Boolean(health.mcp && health.mcp.enabled);
            const rag = Boolean(health.rag && health.rag.enabled);
            parts.push(item(mcp, `MCP ${mcp ? "enabled" : "off"}`), item(rag, `RAG ${rag ? "enabled" : "off"}`));
        }
        status.innerHTML = parts.join("");
    } catch (error) {
        status.innerHTML = `<span class="svc"><span class="dot dot-off"></span>fraud-service offline</span>`;
        const banner = byId("offline-banner");
        banner.innerHTML = `<strong>Can't reach fraud-service at ${esc(API)}.</strong>
            Start it with <code>docker compose up -d</code>, then reload this page.`;
        banner.classList.remove("is-hidden");
    }
}

// Any [data-close] button closes the dialog it sits in.
document.addEventListener("click", (event) => {
    const closer = event.target.closest("[data-close]");
    if (closer) closer.closest("dialog").close();
});
