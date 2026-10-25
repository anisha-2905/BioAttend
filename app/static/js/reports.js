(function () {
  let lock = false;

  function rgba(hex, a) {
    hex = (hex || "").replace("#", "").trim();
    if (hex.length === 3) hex = hex.split("").map(h => h + h).join("");
    const r = parseInt(hex.slice(0, 2), 16) || 0;
    const g = parseInt(hex.slice(2, 4), 16) || 0;
    const b = parseInt(hex.slice(4, 6), 16) || 0;
    return `rgba(${r},${g},${b},${a})`;
  }

  function readJsonEl(id, fallback) {
    try {
      const el = document.getElementById(id);
      return el && el.textContent ? JSON.parse(el.textContent) : fallback;
    } catch {
      return fallback;
    }
  }

  function ensureChartJs(cb, tries = 0) {
    if (window.Chart) return cb();
    if (tries > 30) return; // gives up quietly
    setTimeout(() => ensureChartJs(cb, tries + 1), 100);
  }

  function destroyIf(canvas) {
    const inst = window.Chart && window.Chart.getChart(canvas);
    if (inst) inst.destroy();
  }

  function initReportsCharts() {
    if (lock) return;
    lock = true;

    const scope       = document.getElementById("teacher-reports");
    const trendCanvas = document.getElementById("reportTrend");
    const pieCanvas   = document.getElementById("reportPie");
    const trendDataEl = document.getElementById("trend-data");
    const kpiDataEl   = document.getElementById("kpi-data");

    // If we're not on the reports partial, get skipped
    if (!scope || !trendCanvas || !pieCanvas || !trendDataEl || !kpiDataEl) {
      lock = false;
      return;
    }

    ensureChartJs(() => {
      // Colors from CSS vars (with sensible fallbacks)
      const cs      = getComputedStyle(scope);
      const accent  = (cs.getPropertyValue("--td-accent")  || "#3b82f6").trim();
      const success = (cs.getPropertyValue("--ta-success") || "#10b981").trim();
      const danger  = (cs.getPropertyValue("--ta-danger")  || "#ef4444").trim();
      const muted   = (cs.getPropertyValue("--td-muted")   || "#98a1b3").trim();

      // Data blobs (provided by the partial)
      const TREND = readJsonEl("trend-data", { labels: [], present: [], absent: [] });
      const KPIS  = readJsonEl("kpi-data",   { present: 0, absent: 0, unmarked: 0 });

      // Cleans old instances first 
      destroyIf(trendCanvas);
      destroyIf(pieCanvas);

      // Pie
      new Chart(pieCanvas.getContext("2d"), {
        type: "doughnut",
        data: {
          labels: ["Present", "Absent", "Unmarked"],
          datasets: [{
            data: [KPIS.present || 0, KPIS.absent || 0, KPIS.unmarked || 0],
            backgroundColor: [success, danger, accent]
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "65%",
          plugins: { legend: { labels: { color: muted } } }
        }
      });

      // Line
      new Chart(trendCanvas.getContext("2d"), {
        type: "line",
        data: {
          labels: Array.isArray(TREND.labels) ? TREND.labels : [],
          datasets: [
            {
              label: "Present",
              data: Array.isArray(TREND.present) ? TREND.present : [],
              borderColor: success,
              backgroundColor: rgba(success, 0.15),
              fill: true,
              tension: 0.35,
              borderWidth: 2,
              pointRadius: 0
            },
            {
              label: "Absent",
              data: Array.isArray(TREND.absent) ? TREND.absent : [],
              borderColor: danger,
              backgroundColor: rgba(danger, 0.10),
              fill: true,
              tension: 0.35,
              borderWidth: 2,
              pointRadius: 0
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { labels: { color: muted } } },
          scales: {
            x: { ticks: { color: muted }, grid: { color: "rgba(148,163,184,.15)" } },
            y: { ticks: { color: muted }, grid: { color: "rgba(148,163,184,.15)" }, beginAtZero: true }
          }
        }
      });

      // Releases the lock shortly after render
      setTimeout(() => { lock = false; }, 300);
    });
  }

  // Run on first page load
  document.addEventListener("DOMContentLoaded", initReportsCharts);

  // Run whenever your loader injects the partial (you already dispatch this)
  window.addEventListener("partial:reports:reload", initReportsCharts);
})();
