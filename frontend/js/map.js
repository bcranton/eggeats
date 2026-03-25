/* =========================================================
   Northernlion Travel Guide — Map JS
   ========================================================= */

const API = "";  // same-origin

// State
let map = null;
let allPins = [];
let markers = [];
let openInfoWindow = null;
let activeFilters = {
  city: "",
  category: "",
  sentiment: "",
  showClosed: false,
};

// Sentiment → marker colour mapping
const SENTIMENT_COLORS = {
  positive: "#4caf50",
  negative: "#f44336",
  neutral: "#9e9e9e",
  mixed:   "#ff9800",
  null:    "#9e9e9e",
};

// ──────────────────────────────────────────────────────────
// Bootstrap: fetch config → load Google Maps → fetch data
// ──────────────────────────────────────────────────────────

async function bootstrap() {
  try {
    const config = await fetch(`${API}/api/config`).then(r => r.json());
    await loadGoogleMaps(config.google_maps_api_key);
    await Promise.all([loadCities(), loadMapData()]);
  } catch (err) {
    console.error("Bootstrap error:", err);
    document.getElementById("loading").innerHTML =
      `<p style="color:#f44336">Failed to load map. Is the server running?</p>`;
  }
}

function loadGoogleMaps(apiKey) {
  return new Promise((resolve, reject) => {
    window.__gmapsReady = resolve;
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&callback=__gmapsReady&loading=async`;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

// ──────────────────────────────────────────────────────────
// Data loading
// ──────────────────────────────────────────────────────────

async function loadCities() {
  const cities = await fetch(`${API}/api/cities`).then(r => r.json());
  const select = document.getElementById("filter-city");
  cities.forEach(city => {
    const opt = document.createElement("option");
    opt.value = city.id;
    opt.textContent = `${city.name}, ${city.country}`;
    select.appendChild(opt);
  });
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

  // Init map on first render (centered on first city or Vancouver default)
  if (!map) {
    const center = visible.length > 0
      ? { lat: visible[0].lat, lng: visible[0].lng }
      : { lat: 49.2827, lng: -123.1207 };  // Vancouver default

    map = new google.maps.Map(document.getElementById("map"), {
      center,
      zoom: 13,
      mapTypeId: "roadmap",
      styles: darkMapStyle(),
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
    });
  }

  // Clear existing markers
  markers.forEach(m => m.setMap(null));
  markers = [];
  if (openInfoWindow) {
    openInfoWindow.close();
    openInfoWindow = null;
  }

  // Add markers
  visible.forEach(pin => {
    const color = SENTIMENT_COLORS[pin.sentiment_summary] || SENTIMENT_COLORS.null;
    const marker = new google.maps.Marker({
      position: { lat: pin.lat, lng: pin.lng },
      map,
      title: pin.name,
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: color,
        fillOpacity: pin.is_closed ? 0.4 : 0.9,
        strokeColor: "#ffffff",
        strokeWeight: 1.5,
        scale: 9,
      },
    });

    marker.addListener("click", () => openBusinessPanel(pin.id));
    markers.push(marker);
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
  document.getElementById("panel-name").textContent = "Loading…";
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
  return { positive: "👍", negative: "👎", neutral: "😐", mixed: "🤔" }[s] || "";
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

// ──────────────────────────────────────────────────────────
// Dark map style
// ──────────────────────────────────────────────────────────

function darkMapStyle() {
  return [
    { elementType: "geometry", stylers: [{ color: "#1a1a2e" }] },
    { elementType: "labels.text.stroke", stylers: [{ color: "#1a1a2e" }] },
    { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
    { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "poi", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#263c3f" }] },
    { featureType: "poi.park", elementType: "labels.text.fill", stylers: [{ color: "#6b9a76" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: "#38414e" }] },
    { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#212a37" }] },
    { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#9ca5b3" }] },
    { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#746855" }] },
    { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#1f2835" }] },
    { featureType: "road.highway", elementType: "labels.text.fill", stylers: [{ color: "#f3d19c" }] },
    { featureType: "transit", elementType: "geometry", stylers: [{ color: "#2f3948" }] },
    { featureType: "transit.station", elementType: "labels.text.fill", stylers: [{ color: "#d59563" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#17263c" }] },
    { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#515c6d" }] },
    { featureType: "water", elementType: "labels.text.stroke", stylers: [{ color: "#17263c" }] },
  ];
}

// ── Start ──────────────────────────────────────────────────
bootstrap();
