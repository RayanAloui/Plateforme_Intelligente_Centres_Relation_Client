// Graphiques Plotly de la plateforme. Chaque <div data-chart="type" data-source="id"> est
// dessine a partir du JSON du <script id="id">. Les zones rechargees par HTMX sont redessinees.
(function () {
  const FONT = { family: "ui-sans-serif, system-ui, sans-serif", size: 12, color: "#334155" };
  const BASE = {
    font: FONT, separators: ", ", margin: { t: 30, r: 10, b: 40, l: 50 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", hovermode: "x unified",
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom" },
    xaxis: { gridcolor: "#f1f5f9", tickformat: "%Hh", hoverformat: "%Hh%M" },
    yaxis: { gridcolor: "#e2e8f0", zeroline: false },
  };
  const CONFIG = { responsive: true, displayModeBar: false };
  const layout = (extra) => Object.assign({}, BASE, extra || {});

  const builders = {
    forecast(d) {
      const t = [
        { x: d.x, y: d.q99, line: { width: 0 }, hoverinfo: "skip", showlegend: false },
        { x: d.x, y: d.q01, fill: "tonexty", fillcolor: "rgba(79,70,229,0.12)", line: { width: 0 }, name: "fourchette 98 %", hoverinfo: "skip" },
        { x: d.x, y: d.q90, line: { width: 0 }, hoverinfo: "skip", showlegend: false },
        { x: d.x, y: d.q10, fill: "tonexty", fillcolor: "rgba(79,70,229,0.28)", line: { width: 0 }, name: "fourchette 80 %", hoverinfo: "skip" },
        { x: d.x, y: d.attendu, name: "prévision", line: { color: "#4f46e5", width: 2.5 } },
      ];
      if (d.observe) t.push({ x: d.x, y: d.observe, name: "réalisé", mode: "markers", marker: { color: "#0f172a", size: 6 } });
      const shapes = (d.anomalies || []).map((a) => ({ type: "rect", xref: "x", yref: "paper", x0: a.x, x1: a.x1, y0: 0, y1: 1,
        fillcolor: a.niveau === 2 ? "rgba(225,29,72,0.10)" : "rgba(245,158,11,0.12)", line: { width: 0 } }));
      return [t, layout({ height: 380, yaxis: Object.assign({}, BASE.yaxis, { title: "appels / 30 min" }), shapes })];
    },
    plan(d) {
      const t = [
        { x: d.x, y: d.volume, type: "bar", name: "appels prévus", yaxis: "y2", marker: { color: "rgba(148,163,184,0.25)" } },
        { x: d.x, y: d.besoin, name: "besoin idéal", line: { shape: "hv", color: "#94a3b8", width: 2, dash: "dot" } },
        { x: d.x, y: d.planifies, name: "agents planifiés", line: { shape: "hv", color: d.couleur, width: 3 } },
      ];
      return [t, layout({ height: 340, margin: { t: 30, r: 55, b: 40, l: 50 }, yaxis: Object.assign({}, BASE.yaxis, { title: "agents" }),
        yaxis2: { overlaying: "y", side: "right", showgrid: false, title: "appels" } })];
    },
    undercap(d) {
      const t = [{ x: d.x, y: d.risque, type: "bar", name: "P(sous-capacité)",
        marker: { color: d.risque.map((v) => (v >= 20 ? "#e11d48" : v >= 10 ? "#f59e0b" : "#cbd5e1")) } }];
      return [t, layout({ height: 200, showlegend: false, yaxis: Object.assign({}, BASE.yaxis, { title: "%", rangemode: "tozero" }) })];
    },
    gantt(d) {
      const t = [{ type: "bar", orientation: "h", base: d.debut, x: d.duree_ms, y: d.libelle,
        marker: { color: "#4f46e5" }, hovertemplate: "%{y}<extra></extra>" }];
      return [t, layout({ height: Math.max(220, 26 * d.libelle.length + 60), showlegend: false, hovermode: "closest",
        margin: { t: 10, r: 10, b: 40, l: 150 }, yaxis: { autorange: "reversed", automargin: true },
        xaxis: Object.assign({}, BASE.xaxis, { type: "date" }) })];
    },
    riskcompare(d) {
      const t = d.series.map((s) => ({ x: s.x, y: s.y, name: s.nom, line: { color: s.couleur, width: 2.5, shape: "hv" } }));
      const shapes = [20, 10].map((y) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
        line: { color: y === 20 ? "#e11d48" : "#f59e0b", dash: "dash", width: 1 } }));
      return [t, layout({ height: 300, shapes, yaxis: Object.assign({}, BASE.yaxis, { title: "P(sous-capacité) %" }) })];
    },
    losses(d) {
      const t = d.series.map((s) => ({ x: s.valeurs, type: "histogram", name: s.nom, opacity: 0.55, nbinsx: 50,
        marker: { color: s.couleur } }));
      const shapes = d.series.map((s) => ({ type: "line", yref: "paper", y0: 0, y1: 1, x0: s.var95, x1: s.var95,
        line: { color: s.couleur, dash: "dash", width: 1.5 } }));
      if (d.reel !== null && d.reel !== undefined) shapes.push({ type: "line", yref: "paper", y0: 0, y1: 1, x0: d.reel, x1: d.reel, line: { color: "#0f172a", width: 3 } });
      return [t, layout({ height: 320, barmode: "overlay", hovermode: "closest", shapes,
        xaxis: { title: "perte de la journée (€)", gridcolor: "#f1f5f9" }, yaxis: Object.assign({}, BASE.yaxis, { title: "scénarios" }) })];
    },
  };

  function renderCharts(root) {
    if (!window.Plotly) return;
    (root || document).querySelectorAll("[data-chart]").forEach((el) => {
      const source = document.getElementById(el.dataset.source);
      if (!source || !builders[el.dataset.chart]) return;
      const [traces, lay] = builders[el.dataset.chart](JSON.parse(source.textContent));
      window.Plotly.react(el, traces, lay, CONFIG);
    });
  }
  window.renderCharts = renderCharts;
  document.addEventListener("DOMContentLoaded", () => renderCharts());
  document.addEventListener("htmx:afterSettle", (e) => renderCharts(e.target));
})();
