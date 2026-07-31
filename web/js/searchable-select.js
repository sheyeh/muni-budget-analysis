// Shared search primitives: a type-ahead dropdown (top-bar authority search, Page 3 municipality
// picker) and a plain substring filter helper (Page 2's category/authority checklists).
const SearchableSelect = (() => {
  function substringFilter(items, query, getLabel) {
    const q = (query || "").trim();
    if (!q) return items;
    return items.filter((item) => getLabel(item).includes(q));
  }

  // Wires a live-filter dropdown onto `inputEl`/`resultsEl`. `items` + `getLabel` define the
  // searchable set; `onSelect(item)` fires on click or Enter-on-single-match; `noMatchText` shows
  // when nothing matches (and no navigation happens).
  function attachTypeahead(inputEl, resultsEl, items, getLabel, onSelect, noMatchText) {
    function render(matches) {
      resultsEl.innerHTML = "";
      if (!matches.length) {
        const empty = document.createElement("div");
        empty.className = "search-result-empty";
        empty.textContent = noMatchText;
        resultsEl.appendChild(empty);
        resultsEl.classList.remove("hidden");
        return;
      }
      for (const item of matches) {
        const row = document.createElement("div");
        row.className = "search-result-row";
        row.textContent = getLabel(item);
        row.addEventListener("click", () => {
          onSelect(item);
          hide();
        });
        resultsEl.appendChild(row);
      }
      resultsEl.classList.remove("hidden");
    }

    function hide() {
      resultsEl.classList.add("hidden");
      resultsEl.innerHTML = "";
    }

    inputEl.addEventListener("input", () => {
      const q = inputEl.value.trim();
      if (!q) {
        hide();
        return;
      }
      render(substringFilter(items, q, getLabel));
    });

    inputEl.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const q = inputEl.value.trim();
      if (!q) return;
      const matches = substringFilter(items, q, getLabel);
      if (matches.length === 1) {
        onSelect(matches[0]);
        hide();
        inputEl.value = "";
      }
    });

    document.addEventListener("click", (e) => {
      if (e.target !== inputEl && !resultsEl.contains(e.target)) hide();
    });

    return { hide };
  }

  return { substringFilter, attachTypeahead };
})();
