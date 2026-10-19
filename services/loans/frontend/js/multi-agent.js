const apiBase = `http://${window.location.hostname}:5002`;
const output = document.getElementById("multi-agent-results");
const modeToggle = document.getElementById("multi-agent-toggle");
const modeState = document.getElementById("multi-agent-state");
const workflowRequestInput = document.getElementById("workflow-request");
const STORAGE_KEY = "multi_agent_mode_enabled";
const ACTIVE_STATES = ["created", "planning", "planned", "working", "executed", "reviewing", "revising", "reviewed"];

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
    output.textContent = "Multi-Agent Mode is OFF. Enable Multi-Agent Mode to run workflows.";
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
    const heading = document.createElement("h3");
    heading.textContent = title;
    const body = document.createElement("pre");
    body.textContent = JSON.stringify(payload, null, 2);
    output.replaceChildren(heading, body);
}

function renderError(title, error) {
    const message = error && error.message ? error.message : String(error);
    const heading = document.createElement("h3");
    heading.textContent = title;
    const body = document.createElement("pre");
    body.textContent = message;
    output.replaceChildren(heading, body);
}

function stageFor(record, role) {
    const stages = Array.isArray(record.stages) ? record.stages : [];
    return [...stages].reverse().find((stage) => stage.role === role) || null;
}

function stageStatus(stage) {
    if (!stage) {
        return "pending";
    }
    if (stage.status === "completed") {
        return "success";
    }
    if (stage.status === "failed" || stage.status === "timed_out") {
        return "error";
    }
    return "running";
}

function plannerResult(record) {
    const stage = stageFor(record, "planner");
    const plan = record.plan || {};
    const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];
    const objective = plan.objective || (stage && stage.output && stage.output.objective) || "";
    const steps = tasks.map((task, index) => `${index + 1}. ${task.title || task.instruction || task.endpoint || task.id}`);
    const parts = [
        `Objective: ${objective || "Plan the requested workflow."}`,
        `Steps: ${steps.length ? steps.join("\n") : "Plan, work, review, human decision."}`,
        `Evidence Required: ${tasks.filter((task) => task.kind === "api").map((task) => task.evidence || task.endpoint).join("; ") || "Evidence defined by the workflow plan."}`,
        "Human Approval: Required.",
    ];
    const fallbackReason = (plan.meta && plan.meta.fallback_reason) || (stage && stage.fallback_reason);
    if (fallbackReason) {
        parts.push(`Fallback Reason: ${fallbackReason}`);
    }
    if (stage && stage.error) {
        parts.push(`Error: ${stage.error}`);
    }
    return {
        agent: "planner_agent",
        human_approval_required: true,
        model: (plan.meta && plan.meta.model) || (stage && stage.model) || "",
        objective,
        plan: parts.join("\n"),
        status: stageStatus(stage),
        steps: [
            { action: "Create workflow plan", agent: "planner_agent", step: 1 },
            { action: "Retrieve feature evidence and generate output", agent: "worker_agent", step: 2 },
            { action: "Review output for risk, correction, retest, and recommendation", agent: "reviewer_agent", step: 3 },
            { action: "Accept, partially accept, or reject", agent: "human_reviewer", step: 4 },
        ],
    };
}

function workerResult(record) {
    const stage = stageFor(record, "worker");
    const result = record.result || {};
    const evidence = Array.isArray(result.evidence) ? result.evidence : [];
    const errors = evidence
        .filter((item) => item.status !== "ok")
        .map((item) => item.error)
        .filter(Boolean);
    const error = (stage && stage.error) || errors.join("; ") || "";
    const status = stageStatus(stage) === "error" || (evidence.length > 0 && errors.length === evidence.length)
        ? "error"
        : stageStatus(stage);
    return {
        agent: "worker_agent",
        error,
        evidence,
        evidence_count: evidence.length,
        human_approval_required: true,
        output: result.answer || "",
        status,
    };
}

function reviewerResult(record) {
    const stage = stageFor(record, "reviewer");
    const review = record.review || {};
    const details = [
        review.summary,
        ...(Array.isArray(review.defects) ? review.defects.map((defect) => `Defect (${defect.severity || "unspecified"}): ${defect.note || defect.about || ""}`) : []),
        ...(Array.isArray(review.risks) ? review.risks.map((risk) => `Risk: ${risk}`) : []),
        ...(Array.isArray(review.revision_notes) ? review.revision_notes.map((note) => `Correction: ${note}`) : []),
        stage && stage.fallback_reason ? `Fallback Reason: ${stage.fallback_reason}` : "",
        stage && stage.error ? `Error: ${stage.error}` : "",
    ].filter(Boolean);
    return {
        agent: "reviewer_agent",
        human_approval_required: true,
        model: (review.meta && review.meta.model) || (stage && stage.model) || "",
        review: details.join("\n"),
        status: stageStatus(stage),
    };
}

function displayWorkflow(record) {
    const stages = Array.isArray(record.stages) ? record.stages : [];
    const durationMs = stages.reduce((total, stage) =>
        total + (typeof stage.duration_seconds === "number" ? stage.duration_seconds * 1000 : 0), 0);
    const decision = record.decision && (record.decision.decision || record.decision.value);
    const humanStage = stageFor(record, "human");
    return {
        duration_ms: Math.round(durationMs),
        human_decision: {
            allowed_values: ["Accept", "Partially Accept", "Reject"],
            required: true,
            status: decision || (humanStage && humanStage.status === "completed" ? "completed" : "pending"),
        },
        participating_agents: ["planner_agent", "worker_agent", "reviewer_agent"],
        planner_result: plannerResult(record),
        reviewer_result: reviewerResult(record),
        status: record.state === "failed" ? "error" : ACTIVE_STATES.includes(record.state) ? "running" : "success",
        timestamp: record.updated_at || record.created_at || "",
        user_request: record.request || "",
        worker_result: workerResult(record),
        workflow_id: record.workflow_id || "",
    };
}

function displayWorkflowStatus(record, metrics) {
    const counts = metrics.counts;
    const workflowHistoryCount = metrics.workflows.total;
    if (!Number.isInteger(counts.history_records)
        || !Number.isInteger(counts.coordination_records)
        || !Number.isInteger(workflowHistoryCount)) {
        throw new Error("Multi-Agent API returned incomplete workflow and audit counts");
    }
    const latestWorkflow = displayWorkflow(record);
    return {
        audit_record_count: counts.history_records + counts.coordination_records,
        latest_workflow: latestWorkflow,
        status: latestWorkflow.status,
        workflow_history_count: workflowHistoryCount,
    };
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
            renderJson("Multi-Agent API: /multi-agent/workflow", started);
            return;
        }
        let record = await getJson(`/api/multi-agent/workflow/${encodeURIComponent(started.workflow_id)}`);
        renderJson("Multi-Agent Workflow", displayWorkflow(record));
        for (let attempt = 0; attempt < 240 && isWorkflowRunning(record); attempt += 1) {
            await sleep(1000);
            record = await getJson(`/api/multi-agent/workflow/${encodeURIComponent(started.workflow_id)}`);
            renderJson("Multi-Agent Workflow", displayWorkflow(record));
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
            renderJson("Multi-Agent API: /multi-agent/workflow/status", summary);
            return;
        }
        const [record, metrics] = await Promise.all([
            getJson(`/api/multi-agent/workflow/${encodeURIComponent(summary.workflow_id)}`),
            getJson("/api/multi-agent/metrics"),
        ]);
        renderJson("Multi-Agent Workflow Status", displayWorkflowStatus(record, metrics));
    } catch (error) {
        renderError("Multi-Agent API Error: /multi-agent/workflow/status", error);
    }
});

loadMode();
if (!isEnabled()) {
    renderDisabledMessage();
}
