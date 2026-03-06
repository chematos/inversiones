/* ─── Estado global ─────────────────────────────────────────────────────────── */
let allApartments = [];
let filteredApartments = [];

/* ─── Inicializar ────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  initDualRange("price-min", "price-max", "price-fill",
    (v) => `U$S ${Number(v).toLocaleString()}`, "price-min-val", "price-max-val");
  initDualRange("rent-min", "rent-max", "rent-fill",
    (v) => `${v}%`, "rent-min-val", "rent-max-val");

  document.getElementById("ggcc-max")?.addEventListener("input", () => {
    const val = document.getElementById("ggcc-max").value;
    document.getElementById("ggcc-max-val").textContent =
      `$U ${Number(val).toLocaleString("es-UY")}/mes`;
    applyFilters();
  });

  document.getElementById("sort")?.addEventListener("change", renderCards);
  document.querySelectorAll(".filter-rooms input").forEach((cb) =>
    cb.addEventListener("change", applyFilters));
  document.getElementById("ggcc-unknown")?.addEventListener("change", applyFilters);
  document.querySelectorAll(".zone-cb").forEach((cb) =>
    cb.addEventListener("change", applyFilters));
  document.getElementById("btn-reset")?.addEventListener("click", resetFilters);
  document.getElementById("btn-reload")?.addEventListener("click", loadData);

  loadData();
});

/* ─── Dual range slider ──────────────────────────────────────────────────────── */
function initDualRange(minId, maxId, fillId, fmt, minValId, maxValId) {
  const minEl = document.getElementById(minId);
  const maxEl = document.getElementById(maxId);
  const fill  = document.getElementById(fillId);

  function update() {
    const lo = +minEl.value, hi = +maxEl.value;
    const min = +minEl.min, max = +minEl.max;
    const pLo = (lo - min) / (max - min) * 100;
    const pHi = (hi - min) / (max - min) * 100;
    fill.style.left  = pLo + "%";
    fill.style.width = (pHi - pLo) + "%";
    document.getElementById(minValId).textContent = fmt(lo);
    document.getElementById(maxValId).textContent = fmt(hi);
  }

  minEl.addEventListener("input", () => {
    if (+minEl.value > +maxEl.value) minEl.value = maxEl.value;
    update(); applyFilters();
  });
  maxEl.addEventListener("input", () => {
    if (+maxEl.value < +minEl.value) maxEl.value = minEl.value;
    update(); applyFilters();
  });

  update();
}

/* ─── Datos ──────────────────────────────────────────────────────────────────── */
async function loadData() {
  setLoadingState();
  try {
    const res = await fetch(`./data/apartments.json?_=${Date.now()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allApartments = data.apartments || [];
    updateLastUpdated(data.last_updated);
    applyDataConfig(data);
    applyFilters();
  } catch (err) {
    showError(err.message);
  }
}

function applyDataConfig(data) {
  // Actualizar rango del slider de precio segun los parametros del scraper
  const minP = data.min_price_usd ?? 75000;
  const maxP = data.max_price_usd ?? 98000;
  ["price-min", "price-max"].forEach((id) => {
    const el = document.getElementById(id);
    el.min = minP;
    el.max = maxP;
    el.step = 1000;
  });
  document.getElementById("price-min").value = minP;
  document.getElementById("price-max").value = maxP;
  initDualRange("price-min", "price-max", "price-fill",
    (v) => `U$S ${Number(v).toLocaleString()}`, "price-min-val", "price-max-val");

  // Generar checkboxes de zonas segun el JSON
  const zonas = data.zonas || [];
  const container = document.getElementById("zone-checkboxes");
  container.innerHTML = zonas.map((zona) => {
    const val = normalizeZone(zona);
    const id  = `zone-${val}`;
    return `<div class="checkbox-item">
      <input type="checkbox" class="zone-cb" id="${id}" value="${val}" checked />
      <label for="${id}">${esc(zona)}</label>
    </div>`;
  }).join("");
  container.querySelectorAll(".zone-cb").forEach((cb) =>
    cb.addEventListener("change", applyFilters));
}

/* ─── Filtros ────────────────────────────────────────────────────────────────── */
function normalizeZone(z) {
  return (z || "").toLowerCase()
    .replace(/á/g,"a").replace(/é/g,"e").replace(/í/g,"i")
    .replace(/ó/g,"o").replace(/ú/g,"u").replace(/ñ/g,"n").trim();
}

function applyFilters() {
  const priceMin = +document.getElementById("price-min").value;
  const priceMax = +document.getElementById("price-max").value;
  const rentMin  = +document.getElementById("rent-min").value;
  const rentMax  = +document.getElementById("rent-max").value;
  const ggccMax  = +document.getElementById("ggcc-max").value;
  const includeGgccUnknown = document.getElementById("ggcc-unknown").checked;

  const rooms = {
    dorm1: document.getElementById("filter-1dorm").checked,
    mono:  document.getElementById("filter-mono").checked,
  };

  const selectedZones = new Set(
    [...document.querySelectorAll(".zone-cb:checked")].map((cb) => cb.value)
  );
  const allZonesUnchecked = selectedZones.size === 0;

  filteredApartments = allApartments.filter((apt) => {
    if (apt.price_usd < priceMin || apt.price_usd > priceMax) return false;
    if (apt.rentability_pct < rentMin || apt.rentability_pct > rentMax) return false;

    const ggcc = apt.gastos_comunes_uyu ?? apt.gastos_comunes_usd;
    if (ggcc !== null && ggcc !== undefined) {
      if (ggcc > ggccMax) return false;
    } else {
      if (!includeGgccUnknown) return false;
    }

    const isMono = isMonoApt(apt);
    if (isMono && !rooms.mono) return false;
    if (!isMono && !rooms.dorm1) return false;

    if (!allZonesUnchecked && !selectedZones.has(normalizeZone(apt.zone))) return false;

    return true;
  });

  renderCards();
}

function isMonoApt(apt) {
  const r = (apt.rooms || "").toLowerCase();
  const t = (apt.title || "").toLowerCase();
  return r.includes("monoambiente") || r.includes("estudio") ||
         t.includes("monoambiente") || t.includes("estudio") ||
         r === "0" || r === "0 dormitorios";
}

/* ─── Render ─────────────────────────────────────────────────────────────────── */
function renderCards() {
  const sortVal = document.getElementById("sort").value;
  const sorted = [...filteredApartments].sort((a, b) => {
    switch (sortVal) {
      case "score":       return b.score - a.score;
      case "rent":        return b.rentability_pct - a.rentability_pct;
      case "price-asc":   return a.price_usd - b.price_usd;
      case "price-desc":  return b.price_usd - a.price_usd;
      case "m2":          return (a.price_per_m2 ?? 999999) - (b.price_per_m2 ?? 999999);
      case "days":        return (b.days_on_market || 0) - (a.days_on_market || 0);
      default:            return b.score - a.score;
    }
  });

  const grid  = document.getElementById("cards-grid");
  const count = document.getElementById("results-count");
  count.innerHTML = `<strong>${sorted.length}</strong> de ${allApartments.length} apartamentos`;

  if (sorted.length === 0) {
    grid.innerHTML = `<div class="state-msg"><h3>Sin resultados</h3><p>Ajusta los filtros para ver mas apartamentos.</p></div>`;
    return;
  }
  grid.innerHTML = sorted.map(cardHTML).join("");
}

function cardHTML(apt) {
  const scoreClass = apt.score >= 65 ? "score-high" : apt.score >= 40 ? "score-mid" : "score-low";
  const rentClass  = apt.rentability_pct >= 8 ? "rent-excellent" :
                     apt.rentability_pct >= 6 ? "rent-good" :
                     apt.rentability_pct >= 4 ? "rent-ok" : "rent-poor";

  const img = apt.thumbnail
    ? `<img class="card-img" src="${esc(apt.thumbnail)}" alt="${esc(apt.title)}" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
    : "";
  const placeholder = `<div class="card-img-placeholder" ${apt.thumbnail ? 'style="display:none"' : ""}>&#127968;</div>`;

  const ggccVal = apt.gastos_comunes_uyu ?? apt.gastos_comunes_usd;
  const ggccStr = ggccVal !== null && ggccVal !== undefined
    ? `<strong>${apt.gastos_comunes_uyu != null ? "$U" : "U$S"} ${ggccVal.toLocaleString("es-UY")}/mes</strong>`
    : `<span style="color:#94a3b8">Sin dato</span>`;

  const rentUyu = apt.estimated_rent_uyu;
  const rentStr = rentUyu
    ? `$U ${rentUyu.toLocaleString("es-UY")}/mes`
    : apt.estimated_rent_usd ? `U$S ${apt.estimated_rent_usd}/mes` : "—";

  const daysStr  = apt.days_on_market ? `${apt.days_on_market}d publicado` : "Fecha desconocida";
  const m2Str    = apt.m2 ? `${apt.m2} m²` : "m² s/d";
  const ppm2Str  = apt.price_per_m2 ? `U$S ${apt.price_per_m2.toLocaleString()}/m²` : "—";

  return `
<div class="apt-card">
  ${img}${placeholder}
  <div class="card-body">
    <div class="card-top">
      <div class="card-price">U$S ${Math.round(apt.price_usd).toLocaleString()} <small>venta</small></div>
      <div class="score-badge ${scoreClass}">${apt.score}<span>score</span></div>
    </div>
    <div class="card-title">${esc(apt.title)}</div>
    <div class="card-badges">
      <span class="badge badge-zone">${esc(apt.zone)}</span>
      <span class="badge badge-days">${daysStr}</span>
    </div>
    <div class="card-stats">
      <div class="stat">
        <div class="stat-label">Rentabilidad anual</div>
        <div class="stat-value ${rentClass}">${apt.rentability_pct}%</div>
      </div>
      <div class="stat">
        <div class="stat-label">Alquiler estimado</div>
        <div class="stat-value">${rentStr}</div>
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
    <a href="${esc(apt.url)}" target="_blank" rel="noopener" class="btn-ver">Ver anuncio →</a>
  </div>
</div>`;
}

function esc(str) {
  return String(str || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/* ─── UI helpers ─────────────────────────────────────────────────────────────── */
function updateLastUpdated(isoStr) {
  const el = document.getElementById("last-updated");
  if (!el) return;
  if (!isoStr) { el.textContent = "Sin datos aun — ejecuta el scraper"; return; }
  const fmt = new Date(isoStr).toLocaleString("es-UY", {
    dateStyle: "medium", timeStyle: "short", timeZone: "America/Montevideo",
  });
  el.textContent = `Actualizado: ${fmt} (UY)`;
}

function setLoadingState() {
  const grid = document.getElementById("cards-grid");
  if (grid) grid.innerHTML = `<div class="state-msg"><h3>Cargando...</h3><p>Obteniendo datos de apartamentos.</p></div>`;
}

function showError(msg) {
  const grid = document.getElementById("cards-grid");
  if (grid) grid.innerHTML = `
    <div class="state-msg">
      <h3>Error al cargar datos</h3>
      <p>${esc(msg)}</p>
      <p style="margin-top:8px">Asegurate de haber ejecutado el scraper al menos una vez.</p>
    </div>`;
  const el = document.getElementById("last-updated");
  if (el) el.textContent = "Error al cargar";
}

function resetFilters() {
  const priceMin = document.getElementById("price-min");
  const priceMax = document.getElementById("price-max");
  priceMin.value = priceMin.min;
  priceMax.value = priceMax.max;
  document.getElementById("rent-min").value  = 0;
  document.getElementById("rent-max").value  = 15;
  document.getElementById("ggcc-max").value  = 30000;
  document.getElementById("ggcc-unknown").checked = true;
  document.getElementById("filter-1dorm").checked = true;
  document.getElementById("filter-mono").checked  = true;
  document.getElementById("sort").value = "score";
  document.querySelectorAll(".zone-cb").forEach((cb) => (cb.checked = true));

  initDualRange("price-min", "price-max", "price-fill",
    (v) => `U$S ${Number(v).toLocaleString()}`, "price-min-val", "price-max-val");
  initDualRange("rent-min", "rent-max", "rent-fill",
    (v) => `${v}%`, "rent-min-val", "rent-max-val");
  document.getElementById("ggcc-max-val").textContent = "$U 30.000/mes";

  applyFilters();
}
