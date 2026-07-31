// ₪/%/per-capita formatting, score→color-band, status badge mapping. Shared by all pages.
const Format = (() => {
  const NIS = new Intl.NumberFormat("he-IL", { maximumFractionDigits: 0 });
  const PCT = new Intl.NumberFormat("he-IL", { style: "percent", maximumFractionDigits: 1 });

  function ils(value) {
    if (value === null || value === undefined) return "—";
    return `₪${NIS.format(value)}`;
  }

  function pct(value) {
    if (value === null || value === undefined) return "—";
    return PCT.format(value);
  }

  function perCapita(value) {
    if (value === null || value === undefined) return "—";
    return `₪${NIS.format(value)} לתושב`;
  }

  function number(value) {
    if (value === null || value === undefined) return "—";
    return NIS.format(value);
  }

  // Score bands: green >=70, orange 40-69, red <40, grey = unassessed (checked_years_count 0 / null score)
  function scoreBand(score) {
    if (score === null || score === undefined) return "grey";
    if (score >= 70) return "green";
    if (score >= 40) return "orange";
    return "red";
  }

  const BAND_COLORS = {
    green: "#2e8b3d",
    orange: "#e08a1e",
    red: "#c62f2f",
    grey: "#b0b0b0",
  };

  function bandColor(band) {
    return BAND_COLORS[band] || BAND_COLORS.grey;
  }

  const STATUS_LABELS = {
    not_checked: "טרם נבדק",
    missing: "חסר",
    summary: "תמצית תקציב",
    detailed: "תקציב מפורט",
  };

  const FORMAT_LABELS = {
    xlsx: "XLS",
    pdf_generated: "PDF מיוצר",
    pdf_scanned: "PDF סרוק",
  };

  // Returns {text, cssClass} for a single year-status cell (Page 1 table).
  function yearBadge(yearEntry) {
    if (!yearEntry || yearEntry.status === "not_checked") {
      return { text: STATUS_LABELS.not_checked, cssClass: "badge-not-checked" };
    }
    if (yearEntry.status === "missing") {
      return { text: STATUS_LABELS.missing, cssClass: "badge-missing" };
    }
    if (yearEntry.status === "summary") {
      return { text: STATUS_LABELS.summary, cssClass: "badge-summary" };
    }
    const count = yearEntry.item_count;
    const text = count ? `${STATUS_LABELS.detailed} (${count} סעיפים)` : STATUS_LABELS.detailed;
    return { text, cssClass: "badge-detailed" };
  }

  function formatLabel(formatKey) {
    if (!formatKey) return "—";
    return FORMAT_LABELS[formatKey] || formatKey;
  }

  // Continuous light->dark blue scale for Page 2's category-value choropleth (value in [min,max]).
  function valueColor(value, min, max) {
    if (value === null || value === undefined || min === max) return "#7fa8d9";
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
    // interpolate #dbe9f7 (light) -> #0b4d8c (dark)
    const from = [0xdb, 0xe9, 0xf7];
    const to = [0x0b, 0x4d, 0x8c];
    const rgb = from.map((c, i) => Math.round(c + (to[i] - c) * t));
    return `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
  }

  return { ils, pct, perCapita, number, scoreBand, bandColor, yearBadge, formatLabel, valueColor, STATUS_LABELS, FORMAT_LABELS };
})();
