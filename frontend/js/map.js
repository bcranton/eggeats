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
// Data loading
// ──────────────────────────────────────────────────────────

async function loadCities() {
  const cities = await fetch(`${API}/api/cities`).then(r => r.json());
  citiesById = Object.fromEntries(cities.map(c => [String(c.id), c]));
  const select = document.getElementById("filter-city");
  cities.forEach(city => {
    const opt = document.createElement("option");
    opt.value = city.id;
    opt.textContent = city.business_count > 0
      ? `${city.name} (${city.business_count})`
      : city.name;
    select.appendChild(opt);
  });

  // Select the first (most-reviewed) city by default
  if (cities.length > 0) {
    const first = cities[0];
    select.value = first.id;
    activeFilters.city = String(first.id);
  }
}

async function loadMapData() {
  const params = new URLSearchParams();
  if (activeFilters.city)      params.set("city_id", activeFilters.city);
  if (activeFilters.category)  params.set("category", activeFilters.category);
  if (activeFilters.sentiment) params.set("sentiment", activeFilters.sentiment);

  const data = await fetch(`${API}/api/map-data?${params}`).then(r => r.json());
  allPins = data;
  renderMap(data);
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
    const el = document.createElement("div");
    el.className = "map-marker";
    el.style.cssText = `
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: ${color};
      border: 2px solid #fff;
      cursor: pointer;
      opacity: ${pin.is_closed ? 0.4 : 0.9};
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
      transition: transform 0.15s;
    `;
    el.addEventListener("mouseenter", () => { el.style.transform = "scale(1.3)"; });
    el.addEventListener("mouseleave", () => { el.style.transform = "scale(1)"; });

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
    if (biz.address) parts.push(escapeHtml(biz.address));
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
  loadMapData();
  // Fly to the selected city
  if (activeFilters.city && map) {
    const city = citiesById[activeFilters.city];
    if (city) {
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
  loadMapData();
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
    loadMapData();
  });
});

document.getElementById("filter-show-closed").addEventListener("change", e => {
  activeFilters.showClosed = e.target.checked;
  renderMap(allPins);
});

document.getElementById("panel-close").addEventListener("click", closePanel);

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
