// RAG Mode for Loans & Credit - Release 1 integration.
// Mirrors the enrolment-app RAG tab: an on/off toggle persisted in
// localStorage plus refresh / retrieve / answer forms that proxy to the
// shared RAG server through the loans backend with the X-RAG-Mode header.
const RAG_BASE = `http://${window.location.hostname}:5002`;
const RAG_STORAGE_KEY = "loans_rag_mode_enabled";

const ragToggle = document.getElementById("rag-mode-toggle");
const ragState = document.getElementById("rag-mode-state");
const ragResult = document.getElementById("rag-result");

function ragEnabled() {
    return ragToggle.checked;
}

function renderRagState() {
    const on = ragEnabled();
    ragState.textContent = on ? "ON" : "OFF";
    ragState.classList.toggle("feature-on", on);
    ragState.classList.toggle("feature-off", !on);
}

function saveRagMode() {
    localStorage.setItem(RAG_STORAGE_KEY, String(ragEnabled()));
}

function loadRagMode() {
    const persisted = localStorage.getItem(RAG_STORAGE_KEY);
    ragToggle.checked = persisted === null ? true : persisted === "true";
    renderRagState();
}

function escRag(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function showRagError(message) {
    ragResult.innerHTML = `<p class="alert alert-error">${escRag(message)}</p>`;
}

function renderRagDisabled() {
    showRagError("RAG Mode is OFF. Enable RAG Mode to run RAG tools.");
}

async function callRag(path, data) {
    const response = await fetch(`${RAG_BASE}${path}`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-RAG-Mode": ragEnabled() ? "on" : "off",
        },
        body: JSON.stringify(data),
    });
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data: body };
}

function confidenceBadge(category) {
    const cls = category === "High" ? "badge-ok"
        : category === "Medium" ? "badge-near"
        : category === "Low" ? "badge-over" : "";
    return `<span class="badge ${cls}">${escRag(category || "Unknown")}</span>`;
}

function citationsList(citations) {
    if (!Array.isArray(citations) || !citations.length) return "";
    const items = citations.map((c) => `
        <li><b>${escRag(c.chunk_id)}</b> &middot; ${escRag(c.title)}
            ${c.source_id ? `(${escRag(c.source_id)})` : ""}</li>`).join("");
    return `<h4>Citations</h4><ul>${items}</ul>`;
}

function evidenceTable(evidence) {
    if (!Array.isArray(evidence) || !evidence.length) return "<p class='empty'>No evidence retrieved.</p>";
    const rows = evidence.map((e) => `
        <tr>
            <td>${escRag(e.rank)}</td>
            <td>${escRag(e.chunk_id)}</td>
            <td>${escRag(e.title)}</td>
            <td class="num">${e.relevance != null ? e.relevance : "-"}</td>
            <td>T${escRag(e.authority_tier ?? "")}</td>
            <td><pre>${escRag(e.text)}</pre></td>
        </tr>`).join("");
    return `<div class="table-scroll"><table><tr><th>#</th><th>Chunk</th><th>Source</th>
        <th>Relevance</th><th>Tier</th><th>Text</th></tr>${rows}</table></div>`;
}

function renderRagResult(title, result, extra = "") {
    ragResult.innerHTML = `<h3>${escRag(title)}</h3>${extra}`;
}

// Refresh corpus
document.getElementById("rag-refresh-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ragEnabled()) { renderRagDisabled(); return; }

    ragResult.innerHTML = "<p class='spinner'>Refreshing corpus&hellip;</p>";
    try {
        const result = await callRag("/api/rag/refresh", {});
        if (!result.ok) return showRagError(result.data.error || `Request failed (${result.status}).`);
        const r = result.data.result || {};
        renderRagResult("RAG Tool: refresh_corpus", result.data, `
            <p>${escRag(r.message || "corpus and index rebuilt")}</p>
            <ul>
                <li>chunks: ${escRag(r.chunks ?? "-")}</li>
                <li>sources: ${escRag(r.sources ?? "-")}</li>
                <li>vector indexed: ${escRag(r.vector_indexed ?? "-")}</li>
                <li>mode: ${escRag(r.mode ?? "-")}</li>
                ${r.vector_error ? `<li>vector error: ${escRag(r.vector_error)}</li>` : ""}
            </ul>`);
    } catch (error) { showRagError(error && error.message ? error.message : String(error)); }
});

// Retrieve evidence (no LLM call)
document.getElementById("rag-retrieve-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ragEnabled()) { renderRagDisabled(); return; }

    const query = document.getElementById("rag-retrieve-query").value.trim();
    if (!query) return;

    ragResult.innerHTML = "<p class='spinner'>Retrieving context&hellip;</p>";
    try {
        const result = await callRag("/api/rag/retrieve", { query: query, k: 5 });
        if (!result.ok) return showRagError(result.data.error || `Request failed (${result.status}).`);
        const r = result.data.result || {};
        renderRagResult("RAG Tool: retrieve_context", result.data, `
            <p class="muted">${escRag(r.retrieved_count ?? 0)} retrieved, ${escRag(r.relevant_count ?? 0)} relevant
                &middot; mode ${escRag(r.retrieval_mode ?? "-")}</p>
            ${evidenceTable(r.evidence)}`);
    } catch (error) { showRagError(error && error.message ? error.message : String(error)); }
});

// Grounded answer with citations
document.getElementById("rag-answer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ragEnabled()) { renderRagDisabled(); return; }

    const query = document.getElementById("rag-answer-query").value.trim();
    if (!query) return;

    ragResult.innerHTML = "<p class='spinner'>Answering with citations&hellip;</p>";
    try {
        const result = await callRag("/api/rag/answer", { query: query, k: 5 });
        if (!result.ok) return showRagError(result.data.error || `Request failed (${result.status}).`);
        const r = result.data.result || {};
        renderRagResult("RAG Tool: answer_question", result.data, `
            ${confidenceBadge(r.confidence_category)}
            <p><b>Question:</b> ${escRag(r.query)}</p>
            <p><b>Answer:</b> ${escRag(r.answer)}</p>
            ${citationsList(r.citations)}
            <p class="muted">${escRag(r.retrieval_summary?.relevant_count ?? 0)} relevant chunks
                &middot; insufficient_context: ${escRag(r.insufficient_context ? "yes" : "no")}
                &middot; model ${escRag(r.generation?.model || "-")}</p>`);
    } catch (error) { showRagError(error && error.message ? error.message : String(error)); }
});

ragToggle.addEventListener("change", () => {
    saveRagMode();
    renderRagState();
    if (!ragEnabled()) renderRagDisabled();
});

loadRagMode();
if (!ragEnabled()) renderRagDisabled();