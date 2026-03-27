/* =========================================================
   Egg Eats — Map JS (Mapbox GL)
   ========================================================= */

const API = "";  // same-origin

// State
let map = null;
let allPins = [];
let currentMarkers = [];
let currentPopup = null;
let citiesById = {};
let activeFilters = {
  city: "",
  category: "",
  sentiment: "",
  showClosed: true,
};
let listViewData = []; // businesses shown in list mode

// Sentiment → marker colour mapping
const SENTIMENT_COLORS = {
  positive: "#4ade80",
  negative: "#c0253a",
  neutral:  "#888899",
  mixed:    "#f59e0b",
  null:     "#888899",
};

// ──────────────────────────────────────────────────────────
// Bootstrap: fetch config → init Mapbox → fetch data
// ──────────────────────────────────────────────────────────

async function bootstrap() {
  try {
    const config = await fetch(`${API}/api/config`).then(r => r.json());
    mapboxgl.accessToken = config.mapbox_access_token;
    await Promise.all([loadCities(), loadMapData()]);
  } catch (err) {
    console.error("Bootstrap error:", err);
    document.getElementById("loading").innerHTML =
      `<p style="color:#f44336">Failed to load map. Is the server running?</p>`;
  }
}

// ──────────────────────────────────────────────────────────
// No-location panel (chains / unlocated businesses)
// ──────────────────────────────────────────────────────────

let noLocationData = null;

async function loadNoLocationData() {
  const params = new URLSearchParams();
  if (activeFilters.city) params.set("city_id", activeFilters.city);
  const data = await fetch(`${API}/api/no-location?${params}`).then(r => r.json());
  noLocationData = data;

  const count = data.length;
  const statBlock = document.getElementById("no-location-stat");
  const mobileBtn = document.getElementById("mobile-noloc-btn");
  if (count > 0) {
    document.getElementById("stat-no-location").textContent = count;
    statBlock.style.display = "";
    if (window.matchMedia("(max-width: 768px)").matches) {
      mobileBtn.style.display = "flex";
    }
  } else {
    statBlock.style.display = "none";
    mobileBtn.style.display = "none";
  }
}

function openNoLocationPanel() {
  if (!noLocationData) return;
  renderNoLocationPanel(noLocationData);
  document.getElementById("no-location-panel").classList.add("open");
  document.getElementById("mobile-overlay").classList.add("active");
  requestAnimationFrame(() => document.getElementById("mobile-overlay").classList.add("visible"));
}

function closeNoLocationPanel() {
  document.getElementById("no-location-panel").classList.remove("open");
  const overlay = document.getElementById("mobile-overlay");
  overlay.classList.remove("visible");
  overlay.addEventListener("transitionend", () => overlay.classList.remove("active"), { once: true });
}

function renderNoLocationPanel(businesses) {
  const body = document.getElementById("no-location-body");
  if (!businesses.length) {
    body.innerHTML = `<p style="color:var(--color-text-muted);padding:20px 16px;font-size:13px;">No unlocated businesses found for this city.</p>`;
    return;
  }

  body.innerHTML = "";
  businesses.forEach(biz => {
    const card = document.createElement("div");
    card.className = "no-location-card";

    const sentimentColor = SENTIMENT_COLORS[biz.sentiment_summary] || SENTIMENT_COLORS.null;
    const sentimentLabel = biz.sentiment_summary ? capitalise(biz.sentiment_summary) : null;

    const badgesHtml = [
      biz.category ? `<span class="badge badge-category">${escapeHtml(biz.category)}</span>` : "",
      sentimentLabel ? `<span class="badge badge-sentiment-${biz.sentiment_summary}">${sentimentEmoji(biz.sentiment_summary)} ${sentimentLabel}</span>` : "",
      biz.is_closed ? `<span class="badge badge-closed">Closed</span>` : "",
    ].filter(Boolean).join("");

    const mentionsHtml = (biz.mentions || []).map(mention => {
      const quotesHtml = (mention.quotes || []).slice(0, 2)
        .map(q => `<div class="quote">"${escapeHtml(q)}"</div>`)
        .join("");
      const timeLabel = mention.timestamp_seconds ? ` (${formatTime(mention.timestamp_seconds)})` : "";
      return `
        <div class="mention-card" style="margin-top:10px; padding-top:10px;">
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No quotes extracted.</div>`}
          <a class="watch-link" href="${mention.youtube_url}" target="_blank" rel="noopener">▶ Watch on YouTube${timeLabel}</a>
        </div>`;
    }).join("");

    card.innerHTML = `
      <div class="no-location-card-header">
        <div class="no-location-card-name">${escapeHtml(biz.name)}</div>
      </div>
      <div class="no-location-card-badges">${badgesHtml}</div>
      ${mentionsHtml}
    `;
    body.appendChild(card);
  });
}

// ──────────────────────────────────────────────────────────
// Data loading
// ──────────────────────────────────────────────────────────

async function loadCities() {
  const cities = await fetch(`${API}/api/cities`).then(r => r.json());
  citiesById = Object.fromEntries(cities.map(c => [String(c.id), c]));
  const select = document.getElementById("filter-city");
  // Clear existing options (in case of reload)
  select.innerHTML = "";
  cities.forEach(city => {
    const opt = document.createElement("option");
    opt.value = city.id;
    if (city.is_virtual) {
      opt.textContent = `📋 ${city.name}`;
    } else {
      opt.textContent = city.business_count > 0
        ? `${city.name} (${city.business_count})`
        : city.name;
    }
    select.appendChild(opt);
  });

  // Select the first non-virtual (most-reviewed) city by default
  const first = cities.find(c => !c.is_virtual) || cities[0];
  if (first) {
    select.value = first.id;
    activeFilters.city = String(first.id);
  }
}

async function loadMapData() {
  const city = citiesById[activeFilters.city];
  if (city && city.is_virtual) {
    await loadListView();
    return;
  }

  const params = new URLSearchParams();
  if (activeFilters.city)      params.set("city_id", activeFilters.city);
  if (activeFilters.category)  params.set("category", activeFilters.category);
  if (activeFilters.sentiment) params.set("sentiment", activeFilters.sentiment);

  const [data] = await Promise.all([
    fetch(`${API}/api/map-data?${params}`).then(r => r.json()),
    loadNoLocationData(),
  ]);
  allPins = data;
  showMapView();
  renderMap(data);
}

// ──────────────────────────────────────────────────────────
// List view (for virtual / no-fixed-location city)
// ──────────────────────────────────────────────────────────

async function loadListView() {
  const params = new URLSearchParams();
  if (activeFilters.city) params.set("city_id", activeFilters.city);

  document.getElementById("loading").classList.remove("hidden");
  try {
    listViewData = await fetch(`${API}/api/no-location?${params}`).then(r => r.json());
  } catch (e) {
    console.error("Failed to load list view data:", e);
    listViewData = [];
  }

  showListView();
  renderListView();
  document.getElementById("loading").classList.add("hidden");
}

function showListView() {
  document.getElementById("map").style.display = "none";
  document.getElementById("list-view").style.display = "flex";
  // Hide the slide-in no-location panel (it's not needed in this mode)
  document.getElementById("no-location-stat").style.display = "none";
  document.getElementById("mobile-noloc-btn").style.display = "none";
}

function showMapView() {
  document.getElementById("map").style.display = "";
  document.getElementById("list-view").style.display = "none";
}

function renderListView() {
  const container = document.getElementById("list-view-body");

  // Apply category and sentiment filters client-side
  let items = listViewData;
  if (!activeFilters.showClosed) items = items.filter(b => !b.is_closed);
  if (activeFilters.category)   items = items.filter(b => b.category === activeFilters.category);
  if (activeFilters.sentiment)  items = items.filter(b => b.sentiment_summary === activeFilters.sentiment);

  // Update stats
  document.getElementById("stat-places").textContent = items.length;
  const totalMentions = items.reduce((sum, b) => sum + b.mentions.length, 0);
  document.getElementById("stat-mentions").textContent = totalMentions;

  if (!items.length) {
    container.innerHTML = `<p class="list-view-empty">No places found for the current filters.</p>`;
    return;
  }

  container.innerHTML = "";
  items.forEach(biz => {
    const card = document.createElement("div");
    card.className = "list-card";

    const sentimentColor = SENTIMENT_COLORS[biz.sentiment_summary] || SENTIMENT_COLORS.null;
    const sentimentLabel = biz.sentiment_summary ? capitalise(biz.sentiment_summary) : null;

    const badgesHtml = [
      biz.category ? `<span class="badge badge-category">${escapeHtml(biz.category)}</span>` : "",
      sentimentLabel ? `<span class="badge badge-sentiment-${biz.sentiment_summary}">${sentimentEmoji(biz.sentiment_summary)} ${sentimentLabel}</span>` : "",
      biz.is_closed ? `<span class="badge badge-closed">Closed</span>` : "",
    ].filter(Boolean).join("");

    const mentionsHtml = (biz.mentions || []).map(mention => {
      const quotesHtml = (mention.quotes || []).slice(0, 2)
        .map(q => `<div class="quote">"${escapeHtml(q)}"</div>`)
        .join("");
      const timeLabel = mention.timestamp_seconds ? ` (${formatTime(mention.timestamp_seconds)})` : "";
      return `
        <div class="mention-card" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--color-border);">
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No quotes extracted.</div>`}
          <a class="watch-link" href="${mention.youtube_url}" target="_blank" rel="noopener">▶ Watch on YouTube${timeLabel}</a>
        </div>`;
    }).join("");

    card.innerHTML = `
      <div class="list-card-dot" style="background:${sentimentColor};"></div>
      <div class="list-card-content">
        <div class="list-card-name">${escapeHtml(biz.name)}</div>
        <div class="list-card-badges">${badgesHtml}</div>
        ${mentionsHtml}
      </div>
    `;
    container.appendChild(card);
  });
}

// ──────────────────────────────────────────────────────────
// Map rendering
// ──────────────────────────────────────────────────────────

function renderMap(pins) {
  // Filter closed if needed
  const visible = activeFilters.showClosed ? pins : pins.filter(p => !p.is_closed);

  // Init map on first render
  if (!map) {
    const defaultCity = citiesById[activeFilters.city];
    const center = defaultCity
      ? [defaultCity.center_lng, defaultCity.center_lat]
      : visible.length > 0
        ? [visible[0].lng, visible[0].lat]
        : [-123.1207, 49.2827];  // fallback

    map = new mapboxgl.Map({
      container: "map",
      style: "mapbox://styles/mapbox/navigation-night-v1",
      center,
      zoom: defaultCity ? defaultCity.default_zoom : 12,
    });

    map.addControl(new mapboxgl.NavigationControl(), "bottom-right");

    // Wait for map to load before adding markers
    map.on("load", () => addMarkers(visible));
    return;
  }

  addMarkers(visible);
}

function addMarkers(visible) {
  // Clear existing markers
  currentMarkers.forEach(m => m.remove());
  currentMarkers = [];
  if (currentPopup) {
    currentPopup.remove();
    currentPopup = null;
  }

  // Add markers
  visible.forEach(pin => {
    const color = SENTIMENT_COLORS[pin.sentiment_summary] || SENTIMENT_COLORS.null;

    // Create custom marker element
    const isTouchDevice = window.matchMedia("(pointer: coarse)").matches;
    const markerSize = isTouchDevice ? 24 : 18;

    // Outer el is the Mapbox anchor — Mapbox sets transform:translate on it for positioning.
    // We must NOT modify el's transform or it jumps off-screen.
    // Instead, scale an inner circle element on hover.
    const el = document.createElement("div");
    el.className = "map-marker";
    el.style.cssText = `width: ${markerSize}px; height: ${markerSize}px; cursor: pointer;`;

    const circle = document.createElement("div");
    circle.style.cssText = `
      width: 100%;
      height: 100%;
      border-radius: 50%;
      background: ${color};
      border: 2px solid #fff;
      opacity: ${pin.is_closed ? 0.4 : 0.9};
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
      transition: transform 0.15s;
    `;
    el.appendChild(circle);

    el.addEventListener("mouseenter", () => { circle.style.transform = "scale(1.3)"; });
    el.addEventListener("mouseleave", () => { circle.style.transform = "scale(1)"; });

    const marker = new mapboxgl.Marker({ element: el })
      .setLngLat([pin.lng, pin.lat])
      .addTo(map);

    el.addEventListener("click", (e) => {
      e.stopPropagation();
      openBusinessPanel(pin.id);
    });

    currentMarkers.push(marker);
  });

  // Update stats
  document.getElementById("stat-places").textContent = visible.length;
  const totalMentions = visible.reduce((sum, p) => sum + p.mention_count, 0);
  document.getElementById("stat-mentions").textContent = totalMentions;

  document.getElementById("loading").classList.add("hidden");
}

// ──────────────────────────────────────────────────────────
// Business detail panel
// ──────────────────────────────────────────────────────────

async function openBusinessPanel(businessId) {
  const panel = document.getElementById("info-panel");
  const body = document.getElementById("panel-body");
  const meta = document.getElementById("panel-meta");

  // Show loading state
  document.getElementById("panel-name").textContent = "Loading\u2026";
  body.innerHTML = "";
  meta.innerHTML = "";
  panel.classList.add("open");

  try {
    const biz = await fetch(`${API}/api/businesses/${businessId}`).then(r => r.json());

    document.getElementById("panel-name").textContent = biz.name;

    // Meta badges
    meta.innerHTML = "";
    if (biz.category) {
      meta.appendChild(makeBadge(biz.category, "badge-category"));
    }
    if (biz.is_closed) {
      meta.appendChild(makeBadge("Permanently Closed", "badge-closed"));
    }

    // Mentions
    body.innerHTML = "";
    if (!biz.mentions || biz.mentions.length === 0) {
      body.innerHTML = `<p style="color:var(--color-text-muted);padding:16px 0;font-size:13px;">No mentions found.</p>`;
    } else {
      biz.mentions.forEach(mention => {
        const card = document.createElement("div");
        card.className = "mention-card";

        // Sentiment badge on the mention
        const sentimentBadge = mention.sentiment
          ? `<span class="badge badge-sentiment-${mention.sentiment}" style="font-size:11px; margin-bottom:8px; display:inline-block;">${sentimentEmoji(mention.sentiment)} ${capitalise(mention.sentiment)}</span>`
          : "";

        // Quotes
        const quotesHtml = (mention.quotes || [])
          .slice(0, 3)
          .map(q => `<div class="quote">"${escapeHtml(q)}"</div>`)
          .join("");

        // Timestamp link
        const timeLabel = mention.timestamp_seconds
          ? ` (${formatTime(mention.timestamp_seconds)})`
          : "";

        card.innerHTML = `
          ${sentimentBadge}
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No direct quotes extracted.</div>`}
          <a class="watch-link" href="${mention.youtube_url}" target="_blank" rel="noopener">
            ▶ Watch on YouTube${timeLabel}
          </a>
        `;
        body.appendChild(card);
      });
    }

    // Address / website
    const addressEl = document.getElementById("panel-address");
    const parts = [];
    if (biz.addresses && biz.addresses.length) {
      parts.push(biz.addresses.map(a => escapeHtml(a)).join(" &bull; "));
    }
    if (biz.website) parts.push(`<a href="${biz.website}" target="_blank" rel="noopener">${escapeHtml(biz.website)}</a>`);
    addressEl.innerHTML = parts.join(" &mdash; ");

  } catch (err) {
    body.innerHTML = `<p style="color:#f44336;padding:16px 0;font-size:13px;">Failed to load business details.</p>`;
    console.error(err);
  }
}

function closePanel() {
  document.getElementById("info-panel").classList.remove("open");
}

// ──────────────────────────────────────────────────────────
// Filter handlers
// ──────────────────────────────────────────────────────────

document.getElementById("filter-city").addEventListener("change", e => {
  activeFilters.city = e.target.value;
  closeNoLocationPanel();
  const city = citiesById[activeFilters.city];
  if (city && city.is_virtual) {
    loadListView();
  } else {
    loadMapData();
    // Fly to the selected city
    if (activeFilters.city && map && city) {
      map.flyTo({
        center: [city.center_lng, city.center_lat],
        zoom: city.default_zoom,
        duration: 1200,
      });
    }
  }
});

document.getElementById("filter-category").addEventListener("change", e => {
  activeFilters.category = e.target.value;
  if (isListViewActive()) { renderListView(); } else { loadMapData(); }
  if (window.matchMedia("(max-width: 768px)").matches) closeFilterDrawer();
});

document.querySelectorAll(".sentiment-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const sentiment = btn.dataset.sentiment;
    if (activeFilters.sentiment === sentiment) {
      activeFilters.sentiment = "";
      btn.classList.remove("active");
    } else {
      document.querySelectorAll(".sentiment-btn").forEach(b => b.classList.remove("active"));
      activeFilters.sentiment = sentiment;
      btn.classList.add("active");
    }
    if (isListViewActive()) { renderListView(); } else { loadMapData(); }
    if (window.matchMedia("(max-width: 768px)").matches) closeFilterDrawer();
  });
});

document.getElementById("filter-show-closed").addEventListener("change", e => {
  activeFilters.showClosed = e.target.checked;
  if (isListViewActive()) { renderListView(); } else { renderMap(allPins); }
});

function isListViewActive() {
  return document.getElementById("list-view").style.display !== "none";
}

document.getElementById("panel-close").addEventListener("click", closePanel);
document.getElementById("no-location-open-btn").addEventListener("click", openNoLocationPanel);
document.getElementById("mobile-noloc-btn").addEventListener("click", openNoLocationPanel);
document.getElementById("no-location-close").addEventListener("click", closeNoLocationPanel);

// ──────────────────────────────────────────────────────────
// Mobile filter drawer
// ──────────────────────────────────────────────────────────

const filterPanel   = document.getElementById("filter-panel");
const mobileOverlay = document.getElementById("mobile-overlay");

// On mobile, move filter panel to <body> so position:fixed isn't clipped
// by app-wrapper's overflow:hidden
if (window.matchMedia("(max-width: 768px)").matches) {
  document.body.appendChild(filterPanel);
}

function injectMobileDrawerUI() {
  if (filterPanel.querySelector(".filter-panel-drag-handle")) return; // already injected
  const handle = document.createElement("div");
  handle.className = "filter-panel-drag-handle";
  filterPanel.prepend(handle);

  const closeBtn = document.createElement("button");
  closeBtn.className = "filter-panel-close";
  closeBtn.setAttribute("aria-label", "Close filters");
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", closeFilterDrawer);
  filterPanel.prepend(closeBtn);
}

function openFilterDrawer() {
  injectMobileDrawerUI();
  filterPanel.classList.add("open");
  mobileOverlay.classList.add("active");
  requestAnimationFrame(() => mobileOverlay.classList.add("visible"));
}

function closeFilterDrawer() {
  filterPanel.classList.remove("open");
  mobileOverlay.classList.remove("visible");
  mobileOverlay.addEventListener("transitionend", () => {
    mobileOverlay.classList.remove("active");
  }, { once: true });
}

document.getElementById("mobile-filter-btn").addEventListener("click", openFilterDrawer);
mobileOverlay.addEventListener("click", () => {
  closeFilterDrawer();
  closeNoLocationPanel();
});

// ──────────────────────────────────────────────────────────
// Utilities
// ──────────────────────────────────────────────────────────

function makeBadge(text, className) {
  const span = document.createElement("span");
  span.className = `badge ${className}`;
  span.textContent = text;
  return span;
}

function sentimentEmoji(s) {
  return { positive: "\uD83D\uDC4D", negative: "\uD83D\uDC4E", neutral: "\uD83D\uDE10", mixed: "\uD83E\uDD14" }[s] || "";
}

function capitalise(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ── Start ──────────────────────────────────────────────────
bootstrap();
