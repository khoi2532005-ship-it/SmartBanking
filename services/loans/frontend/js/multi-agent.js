const apiBase = window.SMARTBANK_SAME_ORIGIN_API ? window.location.origin : `http://${window.location.hostname}:5002`;
const output = document.getElementById("multi-agent-results");
const modeToggle = document.getElementById("multi-agent-toggle");
const modeState = document.getElementById("multi-agent-state");
const workflowRequestInput = document.getElementById("workflow-request");
const STORAGE_KEY = "multi_agent_mode_enabled";
const ACTIVE_STATES = ["created", "planning", "planned", "working", "executed", "reviewing", "revising", "reviewed"];
const STATE_LABELS = {
    awaiting_human_review: "Awaiting review",
    partially_accepted: "Partially accepted",
};

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
    const message = document.createElement("p");
    message.className = "alert alert-warn";
    message.textContent = "Multi-Agent Mode is OFF. Enable Multi-Agent Mode to run workflows.";
    output.replaceChildren(message);
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

function renderError(title, error) {
    const message = error && error.message ? error.message : String(error);
    const heading = document.createElement("h3");
    heading.textContent = title;
    const body = document.createElement("p");
    body.className = "alert alert-error";
    body.textContent = message;
    output.replaceChildren(heading, body);
}

function textElement(tag, text, className = "") {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text == null ? "" : String(text);
    return element;
}

function addSection(parent, title, content) {
    if (!content) return;
    const section = document.createElement("section");
    section.className = "ma-section";
    section.append(textElement("h4", title), content);
    parent.append(section);
}

function addList(values, renderItem = (value) => String(value)) {
    if (!Array.isArray(values) || !values.length) return null;
    const list = document.createElement("ul");
    values.forEach((value) => list.append(textElement("li", renderItem(value))));
    return list;
}

function addTextSection(parent, title, value, emptyMessage = "") {
    const text = value == null || value === "" ? emptyMessage : String(value);
    if (text) addSection(parent, title, textElement("p", text, value ? "" : "muted"));
}

function stageFor(record, role) {
    const stages = Array.isArray(record.stages) ? record.stages : [];
    return [...stages].reverse().find((stage) => stage.role === role) || null;
}

function stageClass(record, role) {
    const stage = stageFor(record, role);
    if (stage && stage.status === "completed") return "is-complete";
    if (stage && ["failed", "timed_out"].includes(stage.status)) return "is-failed";
    if (stage) return "is-current";
    if (role === "human" && record.state === "awaiting_human_review") return "is-current";
    if (role === "human" && record.decision) return "is-complete";
    return "";
}

function stageLabel(record, role, label) {
    const stage = stageFor(record, role);
    let status = stage ? stage.status.replaceAll("_", " ") : "pending";
    if (role === "human" && record.state === "awaiting_human_review") status = "awaiting decision";
    if (role === "human" && record.decision) status = record.decision.decision || record.decision.value || "decided";
    return textElement("span", `${label}: ${status}`, `ma-stage ${stageClass(record, role)}`);
}

function renderEvidence(parent, evidence) {
    if (!Array.isArray(evidence) || !evidence.length) return;
    const table = document.createElement("table");
    const header = document.createElement("tr");
    ["Task", "Source", "Status", "Details"].forEach((label) => header.append(textElement("th", label)));
    table.append(header);

    evidence.forEach((item) => {
        const row = document.createElement("tr");
        const detail = item.status === "ok"
            ? [item.http_status ? `HTTP ${item.http_status}` : "", item.duration_seconds != null ? `${item.duration_seconds}s` : ""].filter(Boolean).join(" · ")
            : (item.error || "Evidence unavailable");
        [item.task_id || "—", item.endpoint || "—", item.status || "unknown", detail || "—"]
            .forEach((value) => row.append(textElement("td", value)));
        table.append(row);
    });
    addSection(parent, "Evidence", table);
}

function renderDecisionControls(record) {
    const section = document.createElement("section");
    section.className = "ma-section";
    section.append(
        textElement("h4", "Human workflow decision"),
        textElement("p", "Review the agent result and choose whether to accept, partially accept, or reject it.")
    );

    const fields = document.createElement("div");
    fields.className = "ma-decision-fields";

    const reviewerField = document.createElement("div");
    const reviewerLabel = textElement("label", "Reviewer");
    reviewerLabel.htmlFor = "ma-reviewer";
    const reviewer = document.createElement("input");
    reviewer.id = "ma-reviewer";
    reviewer.name = "reviewer";
    reviewer.type = "text";
    reviewer.maxLength = 60;
    reviewer.autocomplete = "name";
    reviewer.placeholder = "Your name (optional)";
    reviewerField.append(reviewerLabel, reviewer);

    const noteField = document.createElement("div");
    const noteLabel = textElement("label", "Decision note");
    noteLabel.htmlFor = "ma-decision-note";
    const note = document.createElement("textarea");
    note.id = "ma-decision-note";
    note.name = "note";
    note.rows = 2;
    note.maxLength = 1000;
    note.placeholder = "Required for Partially accept";
    noteField.append(noteLabel, note);
    fields.append(reviewerField, noteField);
    section.append(fields);

    const message = document.createElement("p");
    message.className = "ma-decision-message";
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    section.append(message);

    const actions = document.createElement("div");
    actions.className = "ma-decision-actions";
    [
        ["accept", "Accept", "btn"],
        ["partially_accept", "Partially accept", "btn btn-secondary"],
        ["reject", "Reject", "btn btn-danger"],
    ].forEach(([decision, label, className]) => {
        const button = textElement("button", label, className);
        button.type = "button";
        button.addEventListener("click", async () => {
            if (decision === "partially_accept" && !note.value.trim()) {
                message.className = "ma-decision-message alert alert-error";
                message.textContent = "Add a note explaining the correction before partially accepting.";
                note.focus();
                return;
            }

            const decisionButtons = [...actions.querySelectorAll("button")];
            decisionButtons.forEach((item) => { item.disabled = true; });
            message.className = "ma-decision-message spinner";
            message.textContent = "Submitting your decision…";
            try {
                await postJson(
                    `/api/multi-agent/workflow/${encodeURIComponent(record.workflow_id)}/review`,
                    { decision, note: note.value.trim(), reviewer: reviewer.value.trim() }
                );
                const updatedRecord = await getJson(
                    `/api/multi-agent/workflow/${encodeURIComponent(record.workflow_id)}`
                );
                renderWorkflow(updatedRecord);
            } catch (error) {
                message.className = "ma-decision-message alert alert-error";
                message.textContent = error && error.message ? error.message : String(error);
                decisionButtons.forEach((item) => { item.disabled = false; });
            }
        });
        actions.append(button);
    });
    section.append(actions);
    return section;
}

function renderWorkflow(record, metrics = null) {
    const card = document.createElement("article");
    card.className = "ma-workflow";

    const header = document.createElement("div");
    header.className = "ma-workflow-header";
    header.append(textElement("h3", "Loan workflow"));
    const state = String(record.state || "unknown");
    const stateClass = state === "failed" || state === "rejected" ? "badge-over"
        : state === "accepted" || state === "partially_accepted" ? "badge-ok" : "badge-near";
    header.append(textElement("span", STATE_LABELS[state] || state.replaceAll("_", " "), `badge ${stateClass} ma-state`));
    card.append(header);

    const meta = document.createElement("div");
    meta.className = "ma-meta muted";
    if (record.workflow_id) meta.append(textElement("span", `Workflow ${record.workflow_id}`, "chip"));
    if (record.context && record.context.customer_id != null) {
        meta.append(textElement("span", `Customer ${record.context.customer_id}`));
    }
    if (record.updated_at || record.created_at) meta.append(textElement("span", record.updated_at || record.created_at));
    card.append(meta);
    if (record.request) card.append(textElement("p", record.request));

    const stages = document.createElement("div");
    stages.className = "ma-stage-list";
    stages.setAttribute("aria-label", "Workflow progress");
    stages.append(
        stageLabel(record, "planner", "Planner"),
        stageLabel(record, "worker", "Worker"),
        stageLabel(record, "reviewer", "Reviewer"),
        stageLabel(record, "human", "Human review"),
    );
    card.append(stages);

    if (record.error) card.append(textElement("p", record.error, "alert alert-error"));
    const stageMessages = ["planner", "worker", "reviewer"].flatMap((role) => {
        const stage = stageFor(record, role);
        if (!stage) return [];
        return [stage.error, stage.fallback_reason]
            .filter(Boolean)
            .map((message) => `${role[0].toUpperCase()}${role.slice(1)}: ${message}`);
    });
    stageMessages.forEach((message) => card.append(textElement("p", message, "alert alert-warn")));

    const plan = record.plan || {};
    if (plan.objective || (Array.isArray(plan.tasks) && plan.tasks.length)) {
        const section = document.createElement("section");
        section.className = "ma-section";
        section.append(textElement("h4", "Plan"));
        if (plan.objective) section.append(textElement("p", plan.objective));
        const tasks = addList(plan.tasks, (task) =>
            [task.title || task.instruction || task.endpoint || task.id, task.kind === "api" ? task.endpoint : ""]
                .filter(Boolean).join(" · "));
        if (tasks) section.append(tasks);
        card.append(section);
    }

    const result = record.result || {};
    renderEvidence(card, result.evidence);
    const findings = addList(result.findings, (finding) => {
        const refs = Array.isArray(finding.evidence) && finding.evidence.length
            ? ` (evidence: ${finding.evidence.join(", ")})` : "";
        return `${finding.statement || ""}${refs}`;
    });
    if (findings) addSection(card, "Findings", findings);
    addTextSection(card, "Worker answer", result.answer, "The worker has not produced an answer yet.");
    const gaps = addList(result.gaps);
    if (gaps) addSection(card, "Gaps", gaps);

    const review = record.review || {};
    if (review.summary || review.verdict
        || (Array.isArray(review.risks) && review.risks.length)
        || (Array.isArray(review.defects) && review.defects.length)
        || (Array.isArray(review.revision_notes) && review.revision_notes.length)) {
        const section = document.createElement("section");
        section.className = "ma-section";
        const heading = document.createElement("h4");
        heading.append(document.createTextNode("Review"));
        if (review.verdict) {
            const verdictClass = ["accept", "pass"].includes(String(review.verdict).toLowerCase()) ? "badge-ok" : "badge-near";
            heading.append(textElement("span", review.verdict, `badge ${verdictClass}`));
        }
        section.append(heading);
        if (review.summary) section.append(textElement("p", review.summary));
        const risks = addList(review.risks);
        if (risks) {
            section.append(textElement("p", "Risks", "muted"), risks);
        }
        const revisions = addList(review.revision_notes);
        if (revisions) {
            section.append(textElement("p", "Revision notes", "muted"), revisions);
        }
        const defects = addList(review.defects, (defect) =>
            `${defect.severity || "Issue"}: ${defect.note || defect.about || ""}`);
        if (defects) {
            section.append(textElement("p", "Defects", "muted"), defects);
        }
        card.append(section);
    }

    if (record.decision) {
        const decision = record.decision.decision || record.decision.value || "completed";
        addTextSection(card, "Human decision",
            `${String(decision).replaceAll("_", " ")}${record.decision.by ? ` · ${record.decision.by}` : ""}`);
        addTextSection(card, "Reviewer note", record.decision.note);
    } else if (record.state === "awaiting_human_review") {
        card.append(renderDecisionControls(record));
    }
    if (record.final_response) {
        addTextSection(card, record.final_response.released ? "Final response" : "Final response withheld",
            record.final_response.answer || record.final_response.correction_note
                || (record.final_response.released ? "No response text was returned." : "The response was withheld."));
    }

    if (metrics && metrics.counts && metrics.workflows) {
        const counts = metrics.counts;
        const total = metrics.workflows.total;
        if (Number.isInteger(counts.history_records) && Number.isInteger(counts.coordination_records) && Number.isInteger(total)) {
            card.append(textElement("p", `${total} workflows · ${counts.history_records + counts.coordination_records} audit records`, "muted"));
        }
    }
    output.replaceChildren(card);
}

function isWorkflowRunning(record) {
    return ACTIVE_STATES.includes(record.state);
}

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function readJsonResponse(res) {
    const text = await res.text();
    let payload;
    try {
        payload = JSON.parse(text);
    } catch {
        if (!res.ok) {
            throw new Error(text || `Request failed with HTTP ${res.status}`);
        }
        return { raw: text };
    }
    if (!res.ok) {
        throw new Error(payload.error || `Request failed with HTTP ${res.status}`);
    }
    return payload;
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
    return readJsonResponse(res);
}

async function getJson(path) {
    const res = await fetch(`${apiBase}${path}`, {
        headers: {
            "X-Multi-Agent-Mode": isEnabled() ? "on" : "off",
        },
    });
    return readJsonResponse(res);
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
        const started = await postJson("/api/multi-agent/workflow", { user_request });
        if (!started.workflow_id) {
            throw new Error("Multi-Agent API did not return a workflow ID.");
        }
        let record = await getJson(`/api/multi-agent/workflow/${encodeURIComponent(started.workflow_id)}`);
        renderWorkflow(record);
        for (let attempt = 0; attempt < 240 && isWorkflowRunning(record); attempt += 1) {
            await sleep(1000);
            record = await getJson(`/api/multi-agent/workflow/${encodeURIComponent(started.workflow_id)}`);
            renderWorkflow(record);
        }
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
        const summary = await getJson("/api/multi-agent/workflow/status");
        if (!summary.workflow_id) {
            throw new Error("Multi-Agent API did not return a workflow ID.");
        }
        const [record, metrics] = await Promise.all([
            getJson(`/api/multi-agent/workflow/${encodeURIComponent(summary.workflow_id)}`),
            getJson("/api/multi-agent/metrics"),
        ]);
        renderWorkflow(record, metrics);
    } catch (error) {
        renderError("Multi-Agent API Error: /multi-agent/workflow/status", error);
    }
});

loadMode();
if (!isEnabled()) {
    renderDisabledMessage();
}
