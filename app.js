/* ─── Estado global ─────────────────────────────────────────────────────────── */
let allApartments = [];
let filteredApartments = [];

const GITHUB_ACTIONS_URL =
  "https://github.com/chematos/inversiones/actions/workflows/scrape.yml";

/* ─── Inicializar ────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  loadData();
  setupEventListeners();
});

async function loadData() {
  setLoadingState();
  try {
    const res = await fetch(`./data/apartments.json?_=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    allApartments = data.apartments || [];
    updateLastUpdated(data.last_updated);
    buildZoneFilter(allApartments);
    applyFilters();
  } catch (err) {
    showError(err.message);
  }
}

/* ─── Event listeners ────────────────────────────────────────────────────────── */
function setupEventListeners() {
  // Sliders
  const sliders = ["price-max", "rent-min", "ggcc-max"];
  sliders.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener("input", () => {
        updateSliderDisplay(id);
        applyFilters();
      });
    }
  });

  // Sort
  document.getElementById("sort")?.addEventListener("change", renderCards);

  // Room type checkboxes
  document.querySelectorAll(".filter-rooms input").forEach((cb) => {
    cb.addEventListener("change", applyFilters);
  });

  // Toggle "incluir sin dato de GGCC"
  document.getElementById("ggcc-unknown")?.addEventListener("change", applyFilters);

  // Reset
  document.getElementById("btn-reset")?.addEventListener("click", resetFilters);

  // Reload
  document.getElementById("btn-reload")?.addEventListener("click", loadData);
}

/* ─── Filtros ────────────────────────────────────────────────────────────────── */
function applyFilters() {
  const priceMax = +document.getElementById("price-max").value;
  const rentMin = +document.getElementById("rent-min").value;
  const ggccMax = +document.getElementById("ggcc-max").value;
  const includeGgccUnknown = document.getElementById("ggcc-unknown").checked;

  // Tipos de habitacion
  const rooms = {
    dorm1: document.getElementById("filter-1dorm").checked,
    mono: document.getElementById("filter-mono").checked,
  };

  // Zonas seleccionadas
  const zoneCheckboxes = document.querySelectorAll(".zone-cb:checked");
  const selectedZones = new Set([...zoneCheckboxes].map((cb) => cb.value));
  const allZonesUnchecked = selectedZones.size === 0;

  filteredApartments = allApartments.filter((apt) => {
    // Precio
    if (apt.price_usd > priceMax) return false;

    // Rentabilidad
    if (apt.rentability_pct < rentMin) return false;

    // Gastos comunes
    if (apt.gastos_comunes_uyu !== null && apt.gastos_comunes_uyu !== undefined) {
      if (apt.gastos_comunes_uyu > ggccMax) return false;
    } else {
      if (!includeGgccUnknown) return false;
    }

    // Tipo de habitacion
    const isMonoambiente = isMonoApt(apt);
    if (isMonoambiente && !rooms.mono) return false;
    if (!isMonoambiente && !rooms.dorm1) return false;

    // Zona
    if (!allZonesUnchecked && !selectedZones.has(apt.zone)) return false;

    return true;
  });

  renderCards();
}

function isMonoApt(apt) {
  const rooms = (apt.rooms || "").toLowerCase();
  const title = (apt.title || "").toLowerCase();
  return (
    rooms.includes("monoambiente") ||
    rooms.includes("estudio") ||
    title.includes("monoambiente") ||
    title.includes("estudio") ||
    rooms === "0" ||
    rooms === "0 dormitorios"
  );
}

/* ─── Render ─────────────────────────────────────────────────────────────────── */
function renderCards() {
  const sortVal = document.getElementById("sort").value;
  const sorted = [...filteredApartments].sort((a, b) => {
    switch (sortVal) {
      case "score":        return b.score - a.score;
      case "rent":         return b.rentability_pct - a.rentability_pct;
      case "price-asc":   return a.price_usd - b.price_usd;
      case "price-desc":  return b.price_usd - a.price_usd;
      case "m2":           return (b.price_per_m2 === null ? 999999 : 0) - (a.price_per_m2 === null ? 999999 : 0) || a.price_per_m2 - b.price_per_m2;
      case "days":         return (b.days_on_market || 0) - (a.days_on_market || 0);
      default:             return b.score - a.score;
    }
  });

  const grid = document.getElementById("cards-grid");
  const count = document.getElementById("results-count");

  count.innerHTML = `<strong>${sorted.length}</strong> de ${allApartments.length} apartamentos`;

  if (sorted.length === 0) {
    grid.innerHTML = `
      <div class="state-msg">
        <h3>Sin resultados</h3>
        <p>Ajusta los filtros para ver mas apartamentos.</p>
      </div>`;
    return;
  }

  grid.innerHTML = sorted.map(cardHTML).join("");
}

function cardHTML(apt) {
  const scoreClass =
    apt.score >= 65 ? "score-high" : apt.score >= 40 ? "score-mid" : "score-low";

  const rentClass =
    apt.rentability_pct >= 8 ? "rent-excellent" :
    apt.rentability_pct >= 6 ? "rent-good" :
    apt.rentability_pct >= 4 ? "rent-ok" : "rent-poor";

  const img = apt.thumbnail
    ? `<img class="card-img" src="${escape(apt.thumbnail)}" alt="${escape(apt.title)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
    : "";
  const placeholder = `<div class="card-img-placeholder" ${apt.thumbnail ? 'style="display:none"' : ""}>&#127968;</div>`;

  const ggccStr = apt.gastos_comunes_uyu !== null && apt.gastos_comunes_uyu !== undefined
    ? `<strong>$U ${apt.gastos_comunes_uyu.toLocaleString("es-UY")}/mes</strong>`
    : `<span style="color:#94a3b8">Sin dato</span>`;

  const daysStr = apt.days_on_market
    ? `${apt.days_on_market}d publicado`
    : "Fecha desconocida";

  const m2Str = apt.m2 ? `${apt.m2} m²` : "m² s/d";
  const ppm2Str = apt.price_per_m2 ? `U$S ${apt.price_per_m2.toLocaleString()}/m²` : "—";
  const roomsStr = apt.rooms || (isMonoApt(apt) ? "Monoambiente" : "1 dorm.");

  return `
<div class="apt-card">
  ${img}${placeholder}
  <div class="card-body">
    <div class="card-top">
      <div>
        <div class="card-price">
          U$S ${Math.round(apt.price_usd).toLocaleString()}
          <small>venta</small>
        </div>
      </div>
      <div class="score-badge ${scoreClass}">
        ${apt.score}
        <span>score</span>
      </div>
    </div>

    <div class="card-title">${escape(apt.title)}</div>

    <div class="card-badges">
      <span class="badge badge-zone">${escape(apt.zone)}</span>
      <span class="badge badge-days">${daysStr}</span>
    </div>

    <div class="card-stats">
      <div class="stat">
        <div class="stat-label">Rentabilidad anual</div>
        <div class="stat-value ${rentClass}">${apt.rentability_pct}%</div>
      </div>
      <div class="stat">
        <div class="stat-label">Alquiler estimado</div>
        <div class="stat-value">$U ${(apt.estimated_rent_uyu || apt.estimated_rent_usd * 43).toLocaleString("es-UY")}/mes</div>
      </div>
      <div class="stat">
        <div class="stat-label">Superficie</div>
        <div class="stat-value">${m2Str}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Precio/m²</div>
        <div class="stat-value">${ppm2Str}</div>
      </div>
    </div>
  </div>

  <div class="card-footer">
    <div class="card-ggcc">GGCC: ${ggccStr}</div>
    <a href="${apt.url}" target="_blank" rel="noopener" class="btn-ver">Ver anuncio →</a>
  </div>
</div>`;
}

function escape(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ─── Filtro de zonas dinamico ──────────────────────────────────────────────── */
function buildZoneFilter(apartments) {
  const zones = [...new Set(apartments.map((a) => a.zone))].sort();
  const container = document.getElementById("zone-checkboxes");
  if (!container) return;

  container.innerHTML = zones
    .map(
      (z) => `
    <div class="checkbox-item">
      <input type="checkbox" class="zone-cb" id="zone-${escape(z)}" value="${escape(z)}" checked>
      <label for="zone-${escape(z)}">${escape(z)}</label>
    </div>`
    )
    .join("");

  container.querySelectorAll(".zone-cb").forEach((cb) => {
    cb.addEventListener("change", applyFilters);
  });
}

/* ─── UI helpers ─────────────────────────────────────────────────────────────── */
function updateSliderDisplay(id) {
  const val = document.getElementById(id).value;
  const display = document.getElementById(id + "-val");
  if (!display) return;

  if (id === "price-max") display.textContent = `U$S ${Number(val).toLocaleString()}`;
  else if (id === "rent-min") display.textContent = `${val}%`;
  else if (id === "ggcc-max") display.textContent = `$U ${Number(val).toLocaleString("es-UY")}/mes`;
}

function updateLastUpdated(isoStr) {
  const el = document.getElementById("last-updated");
  if (!el) return;
  if (!isoStr) {
    el.textContent = "Sin datos aun — ejecuta el scraper";
    return;
  }
  const d = new Date(isoStr);
  const fmt = d.toLocaleString("es-UY", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Montevideo",
  });
  el.textContent = `Actualizado: ${fmt} (UY)`;
}

function setLoadingState() {
  const grid = document.getElementById("cards-grid");
  if (!grid) return;
  grid.innerHTML = `
    <div class="state-msg">
      <h3>Cargando...</h3>
      <p>Obteniendo datos de apartamentos.</p>
    </div>`;
}

function showError(msg) {
  const grid = document.getElementById("cards-grid");
  if (!grid) return;
  grid.innerHTML = `
    <div class="state-msg">
      <h3>Error al cargar datos</h3>
      <p>${escape(msg)}</p>
      <p style="margin-top:8px">Asegurate de haber ejecutado el scraper al menos una vez.</p>
    </div>`;
  document.getElementById("last-updated").textContent = "Error al cargar";
}

function resetFilters() {
  document.getElementById("price-max").value = 98000;
  document.getElementById("rent-min").value = 0;
  document.getElementById("ggcc-max").value = 30000;
  document.getElementById("ggcc-unknown").checked = true;
  document.getElementById("filter-1dorm").checked = true;
  document.getElementById("filter-mono").checked = true;
  document.getElementById("sort").value = "score";

  ["price-max", "rent-min", "ggcc-max"].forEach(updateSliderDisplay);

  document.querySelectorAll(".zone-cb").forEach((cb) => (cb.checked = true));

  applyFilters();
}
