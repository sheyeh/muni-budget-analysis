// Page 3 — לפי רשות (By Authority). Pick one municipality → treemap + pie + trend line for its
// budget, source files per year, link to its official website. Default: empty-state prompt (no
// auto-picked municipality — guessing one would be more confusing than a clear prompt).
const PageAuthority = (() => {
  let initialized = false;
  let containerRef = null;
  let municipalities = [];
  let authorityAll = {};
  let selectedMuniId = null;
  let selectedCategoryCodes = new Set(); // which trend series to show; empty set = show all
  let mode = "total_ils";

  const MODE_LABELS = {
    total_ils: "סכום כולל",
    pct_of_budget: "באחוזים מתקציב הרשות",
    per_capita: "בשקלים לתושב",
  };

  function muniById(id) {
    return municipalities.find((m) => m.muni_id === id);
  }

  function formatValue(v) {
    if (v === null || v === undefined) return "—";
    if (mode === "total_ils") return Format.ils(v);
    if (mode === "pct_of_budget") return Format.pct(v);
    return Format.perCapita(v);
  }

  function valuesKeyForMode() {
    return { total_ils: "values_total", pct_of_budget: "values_pct_of_budget", per_capita: "values_per_capita" }[mode];
  }

  function selectMuni(muniId) {
    selectedMuniId = muniId;
    selectedCategoryCodes = new Set();
    window.location.hash = `#/authority?muni_id=${encodeURIComponent(muniId)}`;
    renderMain();
    renderCategoryFilter();
  }

  function renderMuniPickerHeader() {
    const m = muniById(selectedMuniId);
    const picker = containerRef.querySelector("#authority-picker-input");
    if (picker) picker.value = m ? m.name : "";
  }

  function renderCategoryFilter() {
    const el = containerRef.querySelector("#authority-category-filter");
    if (!el) return;
    const bundle = authorityAll[selectedMuniId];
    if (!bundle || !bundle.has_pipeline_data) {
      el.innerHTML = "";
      return;
    }
    const codes = bundle.trend.series.map((s) => ({ code: s.code, label: s.label }));
    el.innerHTML = codes
      .map(
        (c) => `
        <label class="checklist-row">
          <input type="checkbox" data-cat-code="${c.code}" ${selectedCategoryCodes.size === 0 || selectedCategoryCodes.has(c.code) ? "checked" : ""} />
          <span>${c.label}</span>
        </label>`
      )
      .join("");
    el.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => {
        // Build explicit selection set from current checkbox states (empty selection = "all").
        const all = codes.map((c) => c.code);
        const checked = [...el.querySelectorAll("input[type=checkbox]:checked")].map((x) => x.dataset.catCode);
        selectedCategoryCodes = checked.length === all.length ? new Set() : new Set(checked);
        renderTrend();
      });
    });
  }

  function renderTreemap(bundle) {
    const el = containerRef.querySelector("#authority-treemap");
    const key = valuesKeyForMode();
    Plotly.newPlot(
      el,
      [
        {
          type: "treemap",
          labels: bundle.treemap.labels,
          parents: bundle.treemap.parents,
          values: bundle.treemap[key].map((v) => (v === null ? 0 : v)),
          branchvalues: "remainder",
          textinfo: "label+value",
        },
      ],
      { margin: { t: 10, r: 10, l: 10, b: 10 } },
      { responsive: true, displaylogo: false }
    );
  }

  function renderPie(bundle) {
    const el = containerRef.querySelector("#authority-pie");
    if (!bundle.pie_latest_year || !bundle.pie_latest_year.slices || !bundle.pie_latest_year.slices.length) {
      el.innerHTML = '<div class="page-placeholder">אין נתונים לתרשים עוגה</div>';
      return;
    }
    el.innerHTML = "";
    Plotly.newPlot(
      el,
      [
        {
          type: "pie",
          labels: bundle.pie_latest_year.slices.map((s) => s.label),
          values: bundle.pie_latest_year.slices.map((s) => s.total_ils),
          textinfo: "label+percent",
        },
      ],
      { title: `פילוח תקציב ${bundle.pie_latest_year.year}`, margin: { t: 40, r: 10, l: 10, b: 10 } },
      { responsive: true, displaylogo: false }
    );
  }

  function renderTrend() {
    const bundle = authorityAll[selectedMuniId];
    const el = containerRef.querySelector("#authority-trend");
    // Trend series objects use plain total_ils/pct_of_budget/per_capita keys (matching `mode`
    // directly) — NOT the treemap's values_total/values_pct_of_budget/values_per_capita naming
    // that valuesKeyForMode() returns. Using that here silently read `undefined` for every trace.
    const key = mode;
    const series = bundle.trend.series.filter((s) => selectedCategoryCodes.size === 0 || selectedCategoryCodes.has(s.code));
    if (!series.length) {
      Plotly.purge(el);
      el.innerHTML = '<div class="page-placeholder">בחרו סעיפים להצגה</div>';
      return;
    }
    el.innerHTML = "";
    Plotly.newPlot(
      el,
      series.map((s) => ({
        type: "scatter",
        mode: "lines+markers",
        name: s.label,
        x: bundle.trend.years,
        y: s[key],
        connectgaps: false,
      })),
      {
        title: `מגמה לפי שנים — ${MODE_LABELS[mode]}`,
        margin: { t: 40, r: 20, l: 50, b: 40 },
        xaxis: { title: "שנה", dtick: 1 },
        yaxis: { title: MODE_LABELS[mode] },
        legend: { orientation: "h" },
      },
      { responsive: true, displaylogo: false }
    );
  }

  function renderSourceFiles(m, bundle) {
    const el = containerRef.querySelector("#authority-source-files");
    const files = bundle ? bundle.source_files : [];
    if (!files.length) {
      el.innerHTML = '<div class="empty-hint">אין קבצי מקור</div>';
      return;
    }
    el.innerHTML = files
      .slice()
      .sort((a, b) => b.year - a.year)
      .map((f) => {
        const badge = Format.yearBadge(f);
        return f.url
          ? `<a class="badge ${badge.cssClass}" href="${f.url}" target="_blank" rel="noopener">${f.year} — ${badge.text}</a>`
          : `<span class="badge ${badge.cssClass}">${f.year} — ${badge.text}</span>`;
      })
      .join("");
  }

  function renderMain() {
    const mainEl = containerRef.querySelector("#authority-main");
    const m = muniById(selectedMuniId);
    renderMuniPickerHeader();

    if (!m) {
      mainEl.innerHTML = '<div class="page-placeholder">בחרו רשות מהרשימה כדי להתחיל</div>';
      containerRef.querySelector("#authority-source-files").innerHTML = "";
      containerRef.querySelector("#authority-website").innerHTML = "";
      return;
    }

    const bundle = authorityAll[m.muni_id];
    renderSourceFiles(m, bundle);
    containerRef.querySelector("#authority-website").innerHTML = m.website_url
      ? `<a href="${m.website_url}" target="_blank" rel="noopener">לאתר הרשות</a>`
      : "";

    if (!bundle || !bundle.has_pipeline_data) {
      mainEl.innerHTML = `<div class="page-placeholder">אין נתונים עבור רשות זו (${m.name})</div>`;
      return;
    }

    mainEl.innerHTML = `
      <div class="authority-charts">
        <div class="authority-row">
          <div id="authority-treemap" class="treemap-canvas"></div>
        </div>
        <div class="mode-toggle" id="authority-mode-toggle">
          ${Object.entries(MODE_LABELS)
            .map(([key, label]) => `<label><input type="radio" name="authmode" value="${key}" ${key === mode ? "checked" : ""}/> ${label}</label>`)
            .join("")}
        </div>
        <div class="authority-row authority-row-split">
          <div id="authority-pie" class="pie-canvas"></div>
          <div id="authority-trend" class="chart-canvas"></div>
        </div>
      </div>
    `;
    renderTreemap(bundle);
    renderPie(bundle);
    renderTrend();

    mainEl.querySelector("#authority-mode-toggle").addEventListener("change", (e) => {
      mode = e.target.value;
      renderTreemap(bundle);
      renderTrend();
    });
  }

  async function render(container, params) {
    containerRef = container;
    const [munisData, authAll] = await Promise.all([Data.getMunicipalities(), Data.getAuthorityAll()]);
    municipalities = munisData;
    authorityAll = authAll;
    selectedMuniId = params && params.muni_id ? params.muni_id : null;

    container.innerHTML = `
      <div class="page-authority">
        <div class="side-panel">
          <div class="side-block">
            <label class="side-label">בחירת רשות להתמקדות</label>
            <input type="text" id="authority-picker-input" placeholder="בחר רשות..." autocomplete="off" />
            <div id="authority-picker-results" class="search-results hidden"></div>
          </div>
          <div class="side-block">
            <label class="side-label">בחירת סעיפים</label>
            <div id="authority-category-filter" class="checklist"></div>
          </div>
          <div class="side-block">
            <label class="side-label">קבצי מקור</label>
            <div id="authority-source-files" class="source-files"></div>
            <div id="authority-website"></div>
          </div>
        </div>
        <div id="authority-main" class="authority-main"></div>
      </div>
    `;

    SearchableSelect.attachTypeahead(
      container.querySelector("#authority-picker-input"),
      container.querySelector("#authority-picker-results"),
      municipalities,
      (m) => m.name,
      (m) => selectMuni(m.muni_id),
      "לא נמצאה רשות"
    );

    renderMain();
    renderCategoryFilter();
  }

  async function show(container, params) {
    if (!initialized) {
      initialized = true;
      await render(container, params);
    } else if (params && params.muni_id && params.muni_id !== selectedMuniId) {
      selectedMuniId = params.muni_id;
      selectedCategoryCodes = new Set();
      renderMain();
      renderCategoryFilter();
    }
    container.classList.remove("hidden");
  }

  function hide(container) {
    container.classList.add("hidden");
  }

  return { show, hide };
})();
