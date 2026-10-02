// SmartBank dashboard helpers shared by the feature pages: overview tiles,
// tabs with counts, sortable columns, money formatting and HTML escaping.
// A plain script (no build step); everything hangs off window.SB.
//
//   <section class="summary-strip is-raised" id="tiles"></section>
//   SB.renderTiles(tilesEl, [{ label, value, sub, tone }])
//
//   <div class="segmented"><button type="button" data-value="" aria-pressed="true">
//       All <span class="seg-count"></span></button> ...</div>
//   const tabs = SB.tabs(tabsEl, (value) => render());   tabs.value, tabs.update(counts)
//
//   <th data-sort="amount"><button type="button" class="sort-btn">Amount</button></th>
//   const sort = SB.sortable(theadEl, { key: "date", dir: "desc" }, () => render());
//   SB.sortBy(rows, (row) => row.amount, sort.dir)
window.SB = (function () {
    const money = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });
    const wholeMoney = new Intl.NumberFormat("en-AU", {
        style: "currency", currency: "AUD", minimumFractionDigits: 0, maximumFractionDigits: 0 });
    const compactMoney = new Intl.NumberFormat("en-AU", {
        style: "currency", currency: "AUD", notation: "compact", maximumFractionDigits: 1 });

    // Everything from an API goes through esc() before it reaches innerHTML.
    function esc(value) {
        return String(value ?? "").replace(/[&<>"']/g, (c) => (
            { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function fmtMoney(value) {
        const amount = Number(value);
        return Number.isFinite(amount) ? money.format(amount) : "–";
    }

    // Headline tiles: $5,000 rather than $5,000.00, and $64.8K past ten thousand.
    function fmtMoneyShort(value) {
        const amount = Number(value);
        if (!Number.isFinite(amount)) return "–";
        if (Math.abs(amount) >= 10000) return compactMoney.format(amount);
        return Number.isInteger(amount) ? wholeMoney.format(amount) : money.format(amount);
    }

    function plural(count, word) {
        return `${count} ${word}${Number(count) === 1 ? "" : "s"}`;
    }

    function titleCase(text) {
        const value = String(text ?? "").toLowerCase();
        return value.charAt(0).toUpperCase() + value.slice(1);
    }

    function debounce(fn, wait = 300) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => fn(...args), wait);
        };
    }

    // Overview tiles: [{ label, value, sub, tone }]; tone "over" or "ok" tints the tile.
    function renderTiles(container, tiles) {
        container.innerHTML = tiles.map((tile) => `
            <div class="stat${tile.tone ? ` stat-${tile.tone}` : ""}">
                <span class="stat-label">${esc(tile.label)}</span>
                <span class="stat-value">${esc(tile.value)}</span>
                <span class="stat-sub">${esc(tile.sub ?? "")}</span>
            </div>`).join("");
    }

    // Tabs: the page writes <button data-value> elements in a .segmented
    // container; this keeps aria-pressed and the counts in step.
    function tabs(container, onChange) {
        const pressed = container.querySelector('button[aria-pressed="true"]');
        let current = pressed ? pressed.dataset.value : "";

        function update(counts) {
            container.querySelectorAll("button[data-value]").forEach((button) => {
                button.setAttribute("aria-pressed", String(button.dataset.value === current));
                const count = button.querySelector(".seg-count");
                if (counts && count) count.textContent = counts[button.dataset.value] || 0;
            });
        }

        container.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-value]");
            if (!button) return;
            current = button.dataset.value;
            update();
            onChange(current);
        });

        return {
            get value() { return current; },
            set value(next) { current = next; update(); },
            update,
        };
    }

    // Sortable header: clicking a th[data-sort] sorts by it; clicking it again
    // reverses. defaults gives a column's first direction (e.g. amounts "desc").
    function sortable(thead, initial, onChange, defaults = {}) {
        const state = { key: initial.key, dir: initial.dir };

        function mark() {
            thead.querySelectorAll("th[data-sort]").forEach((th) => {
                if (th.dataset.sort === state.key) {
                    th.setAttribute("aria-sort", state.dir === "asc" ? "ascending" : "descending");
                } else {
                    th.removeAttribute("aria-sort");
                }
            });
        }

        thead.addEventListener("click", (event) => {
            const th = event.target.closest("th[data-sort]");
            if (!th) return;
            if (th.dataset.sort === state.key) {
                state.dir = state.dir === "asc" ? "desc" : "asc";
            } else {
                state.key = th.dataset.sort;
                state.dir = defaults[state.key] || "asc";
            }
            mark();
            onChange(state);
        });

        mark();
        state.mark = mark;
        return state;
    }

    // A sorted copy; valueOf returns a string or a number for each row.
    function sortBy(rows, valueOf, dir) {
        const direction = dir === "asc" ? 1 : -1;
        return [...rows].sort((a, b) => {
            const x = valueOf(a);
            const y = valueOf(b);
            const order = typeof x === "string" ? x.localeCompare(y) : x - y;
            return order * direction;
        });
    }

    // { "": total, key: count, ... } for the tabs.
    function countBy(rows, keyOf) {
        const counts = { "": rows.length };
        rows.forEach((row) => {
            const key = keyOf(row);
            counts[key] = (counts[key] || 0) + 1;
        });
        return counts;
    }

    return { esc, fmtMoney, fmtMoneyShort, plural, titleCase, debounce, renderTiles, tabs, sortable, sortBy, countBy };
})();
