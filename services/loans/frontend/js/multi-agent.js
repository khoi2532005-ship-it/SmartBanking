const apiBase = `http://${window.location.hostname}:5002`;
const output = document.getElementById("multi-agent-results");
const modeToggle = document.getElementById("multi-agent-toggle");
const modeState = document.getElementById("multi-agent-state");
const workflowRequestInput = document.getElementById("workflow-request");
const STORAGE_KEY = "multi_agent_mode_enabled";

function isEnabled() {
    return modeToggle.checked;
}

function renderState() {
    if (isEnabled()) {
        modeState.textContent = "ON";
        modeState.classList.add("feature-on");
        modeState.classList.remove("feature-off");
    } else {
        modeState.textContent = "OFF";
        modeState.classList.add("feature-off");
        modeState.classList.remove("feature-on");
    }
}

function renderDisabledMessage() {
    output.innerHTML = "<p>Multi-Agent Mode is OFF. Enable Multi-Agent Mode to run workflows.</p>";
}

function saveMode() {
    localStorage.setItem(STORAGE_KEY, String(isEnabled()));
}

function loadMode() {
    const persisted = localStorage.getItem(STORAGE_KEY);
    if (persisted === null) {
        modeToggle.checked = true;
    } else {
        modeToggle.checked = persisted === "true";
    }
    renderState();
}

function renderJson(title, payload) {
    output.innerHTML = `<h3>${title}</h3><pre>${JSON.stringify(payload, null, 2)}</pre>`;
}

function renderError(title, error) {
    const message = error && error.message ? error.message : String(error);
    output.innerHTML = `<h3>${title}</h3><pre>${message}</pre>`;
}

async function postJson(path, data) {
    const res = await fetch(`${apiBase}${path}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-Multi-Agent-Mode": isEnabled() ? "on" : "off",
        },
        body: JSON.stringify(data),
    });
    const text = await res.text();
    try {
        return JSON.parse(text);
    } catch {
        return { raw: text };
    }
}

async function getJson(path) {
    const res = await fetch(`${apiBase}${path}`, {
        headers: {
            "X-Multi-Agent-Mode": isEnabled() ? "on" : "off",
        },
    });
    const text = await res.text();
    try {
        return JSON.parse(text);
    } catch {
        return { raw: text };
    }
}

modeToggle.addEventListener("change", () => {
    saveMode();
    renderState();

    if (!isEnabled()) {
        renderDisabledMessage();
    }
});

document.querySelectorAll("[data-sample-request]").forEach((button) => {
    button.addEventListener("click", () => {
        workflowRequestInput.value = button.dataset.sampleRequest || "";
        workflowRequestInput.focus();
    });
});

document.getElementById("workflow-form").addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!isEnabled()) {
        renderDisabledMessage();
        return;
    }

    try {
        const user_request = document.getElementById("workflow-request").value.trim();
        const payload = await postJson("/multi-agent/workflow", { user_request });
        renderJson("Multi-Agent API: /multi-agent/workflow", payload);
    } catch (error) {
        renderError("Multi-Agent API Error: /multi-agent/workflow", error);
    }
});

document.getElementById("status-form").addEventListener("submit", async (e) => {
    e.preventDefault();

    if (!isEnabled()) {
        renderDisabledMessage();
        return;
    }

    try {
        const payload = await getJson("/multi-agent/workflow/status");
        renderJson("Multi-Agent API: /multi-agent/workflow/status", payload);
    } catch (error) {
        renderError("Multi-Agent API Error: /multi-agent/workflow/status", error);
    }
});

loadMode();
if (!isEnabled()) {
    renderDisabledMessage();
}