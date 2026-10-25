$(document).ready(function () {
  console.log("jQuery ready!");
});

// Counters 
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll('.count').forEach(counter => {
    const target = +counter.getAttribute('data-target') || 0;
    const duration = 700;
    const stepTime = Math.max(20, Math.floor(duration / (target || 1)));
    let current = 0;

    const step = () => {
      current += Math.ceil(target / (duration / stepTime));
      if (current < target) {
        counter.innerText = current;
        setTimeout(step, stepTime);
      } else {
        counter.innerText = target;
      }
    };

    step();
  });

// Progress ring (robust, works on partial reloads too) 
function initProgressRings() {
  document.querySelectorAll('.progress-ring').forEach(function (el) {
    const ring = el.querySelector('.ring');
    if (!ring) return;

    // Percent from data attribute, clamped 0..100
    let percent = Number(el.dataset.percent);
    if (!isFinite(percent)) percent = 0;
    percent = Math.max(0, Math.min(100, percent));

    // Prefer actual path length (works even if r/baseVal is 0)
    let length = 0;
    try {
      length = typeof ring.getTotalLength === 'function' ? ring.getTotalLength() : 0;
    } catch (_) {}
    if (!length) {
      // Fallback to circle math if getTotalLength not available
      const r = (ring.r && ring.r.baseVal && ring.r.baseVal.value) ? ring.r.baseVal.value : 52;
      length = 2 * Math.PI * r;
    }

    ring.style.strokeDasharray = `${length}`;
    const offset = length * (1 - (percent / 100));
    ring.style.strokeDashoffset = `${offset}`;
  });
}

// Runs on normal load
document.addEventListener('DOMContentLoaded', initProgressRings);
window.addEventListener('load', initProgressRings);

// Also re-run when partials are injected into #main-content
(function observePartials() {
  const host = document.getElementById('main-content') || document.body;
  const mo = new MutationObserver(() => initProgressRings());
  mo.observe(host, { childList: true, subtree: true });
})();


// Student Modal Logic
$(document).on("click", "#addStudentBtn", function () {
  $("#studentModal").removeClass("d-none");
});

$(document).on("click", ".close-student-modal", function () {
  $("#studentModal").addClass("d-none");
});

// Handle form submission
$(document).on("submit", "#studentForm", async function (e) {
  e.preventDefault();

  const formData = new FormData(this);

  try {
    const response = await fetch($(this).attr("action") || "{{ url_for('routes.add_student') }}", {
      method: "POST",
      body: formData
    });

    const data = await response.json();

    if (data.error) {
      alert(data.error);
    } else {
      const row = `
        <tr>
          <td>${data.roll_number}</td>
          <td>${data.full_name}</td>
          <td>${data.department}</td>
          <td>${data.email}</td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-primary">View</button>
            <button class="btn btn-sm btn-outline-secondary">Edit</button>
          </td>
        </tr>`;
      $("table tbody").append(row);
      $("#studentModal").addClass("d-none");
      this.reset();
    }
  } catch (err) {
    console.error("Error submitting student:", err);
    alert("Failed to add student. Try again.");
  }
});

document.getElementById('studentSearch').addEventListener('keyup', function() {
  const filter = this.value.toLowerCase();
  const rows = document.querySelectorAll('#studentTableBody tr');

  rows.forEach(row => {
    const roll = row.cells[0].textContent.toLowerCase();
    const name = row.cells[1].textContent.toLowerCase();

    if (roll.includes(filter) || name.includes(filter)) {
      row.style.display = '';
    } else {
      row.style.display = 'none';
    }
  });
});

document.querySelector("#teacher-attendance .btn-primary").addEventListener("click", () => {
  const data = [];
  document.querySelectorAll("#teacher-attendance tbody tr").forEach(row => {
    const id = row.getAttribute("data-student-id");
    const status = row.getAttribute("data-attendance-status") || "unmarked";
    data.push({ id, status });
  });

  fetch("/teacher/attendance/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records: data })
  })
  .then(res => res.json())
  .then(resp => {
    alert(resp.message || "Attendance saved!");
  });
});

// TEACHER REPORTS , build charts when partial appears 
(function () {
  // prevents duplicates if this file loads twice
  if (window.__reportsBoot) return;
  window.__reportsBoot = true;

  function readJsonTag(id, fallback) {
    try {
      const el = document.getElementById(id);
      return el && el.textContent ? JSON.parse(el.textContent) : fallback;
    } catch {
      return fallback;
    }
  }

  function rgba(hex, a) {
    hex = (hex || "").replace("#", "").trim();
    if (hex.length === 3) hex = hex.split("").map(h => h + h).join("");
    const r = parseInt(hex.slice(0, 2), 16) || 0;
    const g = parseInt(hex.slice(2, 4), 16) || 0;
    const b = parseInt(hex.slice(4, 6), 16) || 0;
    return `rgba(${r},${g},${b},${a})`;
  }

  function buildReportsCharts() {
    const scope = document.getElementById("teacher-reports");
    if (!scope) return false; // reports page not present

    const trendCanvas = document.getElementById("reportTrend");
    const pieCanvas   = document.getElementById("reportPie");
    const trendTag    = document.getElementById("trend-data");
    const kpiTag      = document.getElementById("kpi-data");

    // need all pieces present
    if (!trendCanvas || !pieCanvas || !trendTag || !kpiTag) return false;
    if (typeof Chart === "undefined") return false;

    const TREND = readJsonTag("trend-data", { labels: [], present: [], absent: [] });
    const KPIS  = readJsonTag("kpi-data",   { present: 0, absent: 0, unmarked: 0 });

    // colors from CSS vars
    const cs      = getComputedStyle(scope);
    const success = (cs.getPropertyValue("--ta-success") || "#10b981").trim();
    const danger  = (cs.getPropertyValue("--ta-danger")  || "#ef4444").trim();
    const accent  = (cs.getPropertyValue("--td-accent")  || "#3b82f6").trim();
    const muted   = (cs.getPropertyValue("--td-muted")   || "#98a1b3").trim();

    // Fallback if server sent empty arrays (avoid blank)
    const labels  = Array.isArray(TREND.labels)  && TREND.labels.length  ? TREND.labels  : ["No data"];
    const present = Array.isArray(TREND.present) && TREND.present.length ? TREND.present : [0];
    const absent  = Array.isArray(TREND.absent)  && TREND.absent.length  ? TREND.absent  : [0];

    // Destroy any existing charts on these canvases
    const exLine = Chart.getChart(trendCanvas);
    if (exLine) exLine.destroy();
    const exPie  = Chart.getChart(pieCanvas);
    if (exPie) exPie.destroy();

    // Build line (trend)
    new Chart(trendCanvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "Present", data: present, borderColor: success, backgroundColor: rgba(success, .15), fill: true, tension: .35, pointRadius: 0, borderWidth: 2 },
          { label: "Absent",  data: absent,  borderColor: danger,  backgroundColor: rgba(danger,  .10), fill: true, tension: .35, pointRadius: 0, borderWidth: 2 }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: muted } } },
        scales: {
          x: { ticks: { color: muted }, grid: { color: "rgba(148,163,184,.15)" } },
          y: { ticks: { color: muted }, grid: { color: "rgba(148,163,184,.15)" }, beginAtZero: true }
        }
      }
    });

    // Build pie 
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
        responsive: true, maintainAspectRatio: false, cutout: "60%",
        plugins: { legend: { labels: { color: muted } } }
      }
    });

    // mark as ready to avoid double-build
    scope.dataset.reportsReady = "1";
    return true;
  }

  // Try now, and also retry a few times / handle slow loads 
  function tryInit(retries = 30) {
    if (document.getElementById("teacher-reports")?.dataset.reportsReady === "1") return;
    if (buildReportsCharts()) return;
    if (retries <= 0) return;
    setTimeout(() => tryInit(retries - 1), 100);
  }

  // Run on normal page load
  document.addEventListener("DOMContentLoaded", () => tryInit());
  window.addEventListener("load", () => tryInit());

  // Observe DOM for SPA/partial injections
  const mo = new MutationObserver(() => tryInit(10));
  mo.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener("partial:reports:ready", () => tryInit(10));
})();
// Custom event listener for partial reloads
window.addEventListener("partial:reports:reload", () => {
  console.log("♻️ Rebuilding charts after partial reload");
  const section = document.getElementById("teacher-reports");
  if (section) {
    // Force clear dataset flag and retry chart initialization
    section.removeAttribute("data-reports-ready");
    const event = new Event("partial:reports:ready");
    window.dispatchEvent(event);
  }
});
}
)

