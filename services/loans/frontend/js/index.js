const tabButtons = Array.from(document.querySelectorAll(".tab-btn"));
const tabNames = tabButtons.map((button) => button.dataset.tab);
const tabFrames = {
    normal: document.getElementById("tab-frame-normal"),
    "ai-mode": document.getElementById("tab-frame-ai-mode"),
    mcp: document.getElementById("tab-frame-mcp"),
    rag: document.getElementById("tab-frame-rag"),
    "multi-agent": document.getElementById("tab-frame-multi-agent"),
};

function resizeFrame(frame) {
    const frameDocument = frame.contentDocument;
    if (!frameDocument) return;

    const bodyHeight = frameDocument.body ? frameDocument.body.scrollHeight : 0;
    frame.style.height = `${Math.max(frameDocument.documentElement.scrollHeight, bodyHeight)}px`;
}

Object.values(tabFrames).forEach((frame) => {
    let resizeObserver;
    frame.addEventListener("load", () => {
        resizeObserver?.disconnect();
        resizeFrame(frame);

        const frameDocument = frame.contentDocument;
        if (!frameDocument) return;

        resizeObserver = new ResizeObserver(() => resizeFrame(frame));
        resizeObserver.observe(frameDocument.documentElement);
        if (frameDocument.body) resizeObserver.observe(frameDocument.body);
    });
});

function activateTab(tabName, updateHash = true) {
    if (!tabFrames[tabName]) return;

    tabButtons.forEach((button) => {
        const selected = button.dataset.tab === tabName;
        button.classList.toggle("is-active", selected);
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
    });

    Object.entries(tabFrames).forEach(([name, frame]) => {
        const selected = name === tabName;
        frame.classList.toggle("is-active", selected);
        frame.hidden = !selected;
        if (selected) resizeFrame(frame);
    });

    if (updateHash && window.location.hash !== `#${tabName}`) {
        window.location.hash = tabName;
    }
}

tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
        activateTab(button.dataset.tab);
    });

    button.addEventListener("keydown", (event) => {
        const currentIndex = tabNames.indexOf(button.dataset.tab);
        let nextIndex;
        if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabNames.length;
        else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabNames.length) % tabNames.length;
        else if (event.key === "Home") nextIndex = 0;
        else if (event.key === "End") nextIndex = tabNames.length - 1;
        else return;

        event.preventDefault();
        const nextButton = tabButtons[nextIndex];
        nextButton.focus();
        activateTab(nextButton.dataset.tab);
    });
});

window.addEventListener("hashchange", () => {
    const tabName = window.location.hash.slice(1);
    if (tabFrames[tabName]) activateTab(tabName, false);
});

const initialTab = window.location.hash.slice(1);
activateTab(tabFrames[initialTab] ? initialTab : "normal", false);