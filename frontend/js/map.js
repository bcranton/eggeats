/* =========================================================
   Egg Eats — Map JS
   ========================================================= */

const API = "";  // same-origin

// Set by bootstrap() based on /api/config map_provider value.
// Either mapboxgl (Mapbox) or maplibregl (OpenFreeMap).
let mapLib = null;

// Extract [MM/DD/YYYY] from a video title; returns a comparable number (YYYYMMDD) or 0
function titleDate(title) {
  const m = (title || "").match(/\[(\d{2})\/(\d{2})\/(\d{4})\]/);
  if (!m) return 0;
  return parseInt(m[3] + m[1] + m[2], 10); // YYYYMMDD
}

// Sort mentions newest-first by date embedded in video title
function sortMentions(mentions) {
  return [...mentions].sort((a, b) => titleDate(b.video_title) - titleDate(a.video_title));
}

// Compute API date_from / date_to strings from activeFilters date settings
function activeDateRange() {
  const today = new Date();
  const fmt = d => d.toISOString().slice(0, 10); // YYYY-MM-DD
  if (activeFilters.datePreset === "week") {
    const d = new Date(today); d.setDate(d.getDate() - 7);
    return { date_from: fmt(d), date_to: fmt(today) };
  }
  if (activeFilters.datePreset === "month") {
    const d = new Date(today); d.setMonth(d.getMonth() - 1);
    return { date_from: fmt(d), date_to: fmt(today) };
  }
  if (activeFilters.datePreset === "year") {
    const d = new Date(today); d.setFullYear(d.getFullYear() - 1);
    return { date_from: fmt(d), date_to: fmt(today) };
  }
  if (activeFilters.datePreset === "custom") {
    return { date_from: activeFilters.dateFrom, date_to: activeFilters.dateTo };
  }
  return { date_from: "", date_to: "" };
}

// Build a YouTube embed URL from a watch URL (https://youtube.com/watch?v=ID&t=Ns)
function ytEmbedUrl(watchUrl) {
  try {
    const u = new URL(watchUrl);
    const videoId = u.searchParams.get("v");
    if (!videoId) return null;
    const start = parseInt(u.searchParams.get("t") || "0", 10);
    return `https://www.youtube.com/embed/${videoId}?start=${start}&autoplay=1`;
  } catch {
    return null;
  }
}

// Toggle an inline YouTube embed below the clicked button
function toggleYtEmbed(btn) {
  const existing = btn.nextElementSibling;
  if (existing && existing.classList.contains("yt-embed-wrap")) {
    existing.remove();
    btn.classList.remove("active");
    return;
  }
  const embedUrl = ytEmbedUrl(btn.dataset.ytUrl);
  if (!embedUrl) return;
  const wrap = document.createElement("div");
  wrap.className = "yt-embed-wrap";
  wrap.innerHTML = `<iframe src="${embedUrl}" frameborder="0" allowfullscreen
    allow="autoplay; encrypted-media" loading="lazy"></iframe>`;
  btn.after(wrap);
  btn.classList.add("active");
}

// CSS custom-property style string for the quote border colour
function quoteColorStyle(sentiment) {
  const color = SENTIMENT_COLORS[sentiment] || SENTIMENT_COLORS.null;
  return `style="--quote-color:${color}"`;
}

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
  search: "",
  datePreset: "",   // "week" | "month" | "year" | "custom" | ""
  dateFrom: "",     // YYYY-MM-DD (custom range)
  dateTo: "",       // YYYY-MM-DD (custom range)
};
let listViewData = []; // businesses shown in list mode
let visiblePins = []; // currently rendered map pins (filtered)
let currentPinIndex = -1; // index into visiblePins for the open panel
let activeMarkerCircle = null; // the circle element of the currently open pin

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
    if (config.map_provider === "openfreemap") {
      mapLib = maplibregl;
    } else {
      mapLib = mapboxgl;
      mapboxgl.accessToken = config.mapbox_access_token;
    }
    await loadCities();
    await loadMapData();
  } catch (err) {
    console.error("Bootstrap error:", err);
    document.getElementById("loading").innerHTML =
      `<p style="color:#f44336">Failed to load map. Is the server running?</p>`;
  }
}

// ──────────────────────────────────────────────────────────
// Unlocated strip (city businesses with no coordinates)
// ──────────────────────────────────────────────────────────

let noLocationData = [];

async function loadNoLocationData() {
  const params = new URLSearchParams();
  if (activeFilters.city) params.set("city_id", activeFilters.city);
  const { date_from, date_to } = activeDateRange();
  if (date_from) params.set("date_from", date_from);
  if (date_to)   params.set("date_to", date_to);
  noLocationData = await fetch(`${API}/api/no-location?${params}`).then(r => r.json());
  renderUnlocatedStrip();
}

function renderUnlocatedStrip() {
  const drawer = document.getElementById("unlocated-drawer");
  const body   = document.getElementById("unlocated-drawer-body");

  let items = noLocationData;
  if (!activeFilters.showClosed) items = items.filter(b => !b.is_closed);
  if (activeFilters.search) {
    const q = activeFilters.search.toLowerCase();
    items = items.filter(b => b.name.toLowerCase().includes(q));
  }
  items = [...items].sort((a, b) => a.name.localeCompare(b.name));

  if (!items.length) {
    drawer.style.display = "none";
    return;
  }

  // Update handle label
  const city = citiesById[activeFilters.city];
  const cityLabel = city ? city.name : "This City";
  const count = items.length;
  document.getElementById("unlocated-drawer-label").textContent =
    `${count} place${count !== 1 ? "s" : ""} without a location in ${cityLabel}`;

  drawer.style.display = "flex";

  // Cap body height to the actual map height so the top is never clipped
  const mapEl = document.getElementById("map");
  if (mapEl) {
    body.style.maxHeight = (mapEl.offsetHeight - 8) + "px";
  }

  // Wire up toggle once (idempotent via flag)
  const handle = document.getElementById("unlocated-drawer-handle");
  if (!handle._drawerBound) {
    handle._drawerBound = true;
    handle.addEventListener("click", () => {
      const isOpen = drawer.classList.toggle("open");
      handle.setAttribute("aria-expanded", String(isOpen));
    });
  }

  // Reset to closed state when re-rendered (city changed)
  drawer.classList.remove("open");
  handle.setAttribute("aria-expanded", "false");

  body.innerHTML = "";
  items.forEach(biz => {
    const card = document.createElement("div");
    card.className = "unlocated-item";

    const sentimentColor = SENTIMENT_COLORS[biz.sentiment_summary] || SENTIMENT_COLORS.null;
    const sentimentLabel = biz.sentiment_summary ? capitalise(biz.sentiment_summary) : null;

    const badgesHtml = [
      biz.category ? `<span class="badge badge-category">${escapeHtml(biz.category)}</span>` : "",
      sentimentLabel ? `<span class="badge badge-sentiment-${biz.sentiment_summary}">${sentimentEmoji(biz.sentiment_summary)} ${sentimentLabel}</span>` : "",
      biz.is_closed ? `<span class="badge badge-closed">Closed</span>` : "",
    ].filter(Boolean).join("");

    const mentionsHtml = sortMentions(biz.mentions || []).map(mention => {
      const quotesHtml = (mention.quotes || [])
        .map(q => `<div class="quote" ${quoteColorStyle(mention.sentiment)}>"${escapeHtml(q)}"</div>`)
        .join("");
      const timeLabel = mention.timestamp_seconds ? ` (${formatTime(mention.timestamp_seconds)})` : "";
      return `
        <div class="mention-card" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--color-border);">
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No quotes extracted.</div>`}
          <button class="watch-link" data-yt-url="${mention.youtube_url}" onclick="toggleYtEmbed(this)">▶ Watch on YouTube${timeLabel}</button>
        </div>`;
    }).join("");

    card.innerHTML = `
      <div class="unlocated-item-header">
        <div class="unlocated-item-dot" style="background:${sentimentColor};"></div>
        <div class="unlocated-item-name">${escapeHtml(biz.name)}</div>
      </div>
      ${badgesHtml ? `<div class="unlocated-item-badges">${badgesHtml}</div>` : ""}
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
  const { date_from, date_to } = activeDateRange();
  if (date_from) params.set("date_from", date_from);
  if (date_to)   params.set("date_to", date_to);

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
  document.getElementById("unlocated-drawer").style.display = "none";
}

function showMapView() {
  document.getElementById("map").style.display = "";
  document.getElementById("list-view").style.display = "none";
}

function renderListView() {
  const container = document.getElementById("list-view-body");

  let items = listViewData;
  if (!activeFilters.showClosed) items = items.filter(b => !b.is_closed);
  if (activeFilters.category)   items = items.filter(b => b.category === activeFilters.category);
  if (activeFilters.sentiment)  items = items.filter(b => b.sentiment_summary === activeFilters.sentiment);
  if (activeFilters.search) {
    const q = activeFilters.search.toLowerCase();
    items = items.filter(b => b.name.toLowerCase().includes(q));
  }
  items = [...items].sort((a, b) => a.name.localeCompare(b.name));

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

    const mentionsHtml = sortMentions(biz.mentions || []).map(mention => {
      const quotesHtml = (mention.quotes || [])
        .map(q => `<div class="quote" ${quoteColorStyle(mention.sentiment)}>"${escapeHtml(q)}"</div>`)
        .join("");
      const timeLabel = mention.timestamp_seconds ? ` (${formatTime(mention.timestamp_seconds)})` : "";
      return `
        <div class="mention-card" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--color-border);">
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No quotes extracted.</div>`}
          <button class="watch-link" data-yt-url="${mention.youtube_url}" onclick="toggleYtEmbed(this)">▶ Watch on YouTube${timeLabel}</button>
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
  let visible = activeFilters.showClosed ? pins : pins.filter(p => !p.is_closed);
  if (activeFilters.search) {
    const q = activeFilters.search.toLowerCase();
    visible = visible.filter(p => p.name.toLowerCase().includes(q));
  }

// Return the IQR-based inlier range for an array of numbers.
function iqrRange(values) {
  const s = [...values].sort((a, b) => a - b);
  const q1 = s[Math.floor(s.length * 0.25)];
  const q3 = s[Math.floor(s.length * 0.75)];
  const iqr = q3 - q1;
  return { lo: q1 - 1.5 * iqr, hi: q3 + 1.5 * iqr };
}

// Fit the map to show all currently visible pins, with padding so pins
// aren't hidden behind the side panels. Uses IQR outlier removal for
// the bounds calc so a single far-away pin doesn't zoom the map way out.
function fitMapToPins() {
  if (!map) return;
  if (visiblePins.length === 0) return;

  if (visiblePins.length === 1) {
    map.flyTo({ center: [visiblePins[0].lng, visiblePins[0].lat], zoom: 14, duration: 800 });
    return;
  }

  // Try to exclude outliers from the bounds calculation (markers still render)
  let pins = visiblePins;
  if (pins.length >= 4) {
    const lngR = iqrRange(pins.map(p => p.lng));
    const latR = iqrRange(pins.map(p => p.lat));
    const inliers = pins.filter(p =>
      p.lng >= lngR.lo && p.lng <= lngR.hi &&
      p.lat >= latR.lo && p.lat <= latR.hi
    );
    // Only use the filtered set if it actually removed something and
    // kept at least half the pins (avoid over-filtering small datasets)
    if (inliers.length < pins.length && inliers.length >= Math.ceil(pins.length / 2)) {
      pins = inliers;
    }
  }

  const lngs = pins.map(p => p.lng);
  const lats = pins.map(p => p.lat);
  const bounds = [
    [Math.min(...lngs), Math.min(...lats)], // SW
    [Math.max(...lngs), Math.max(...lats)], // NE
  ];
  map.fitBounds(bounds, { padding: 60, duration: 800, maxZoom: 15 });
}

// Init map on first render
  if (!map) {
    const defaultCity = citiesById[activeFilters.city];
    const center = defaultCity
      ? [defaultCity.center_lng, defaultCity.center_lat]
      : visible.length > 0
        ? [visible[0].lng, visible[0].lat]
        : [-123.1207, 49.2827];  // fallback

    const mapStyle = (mapLib === maplibregl)
      ? "https://tiles.openfreemap.org/styles/fiord"
      : "mapbox://styles/mapbox/navigation-night-v1";

    map = new mapLib.Map({
      container: "map",
      style: mapStyle,
      center,
      zoom: defaultCity ? defaultCity.default_zoom : 12,
    });

    map.addControl(new mapLib.NavigationControl(), "bottom-right");

    // Wait for map to load before adding markers
    map.on("load", () => { addMarkers(visible); fitMapToPins(); });
    return;
  }

  addMarkers(visible);
  fitMapToPins();
}

function addMarkers(visible) {
  // Clear existing markers
  currentMarkers.forEach(m => m.remove());
  currentMarkers = [];
  if (currentPopup) {
    currentPopup.remove();
    currentPopup = null;
  }

  visiblePins = visible;

  // Filter to pins geographically close to the city centre so that
  // businesses with stale/wrong coordinates from other cities don't
  // pollute the cycle and teleport the user across the world.
  const city = citiesById[activeFilters.city];
  if (city && city.center_lat && city.center_lng) {
    visiblePins = visible.filter(p =>
      Math.abs(p.lat - city.center_lat) < 1.5 &&
      Math.abs(p.lng - city.center_lng) < 1.5
    );
  }

  // Sort west → east so the cycle arrows feel geographic
  visiblePins.sort((a, b) => a.lng - b.lng);

  // Re-assign stable indices based on the filtered list so clicks and
  // the cycle counter stay in sync. Key by lat:lng so multi-location
  // businesses each get their own index.
  const pinIndexMap = new Map(visiblePins.map((p, i) => [`${p.lat}:${p.lng}`, i]));

  // Add markers
  visible.forEach((pin) => {
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
    el.addEventListener("mouseleave", () => {
      if (circle !== activeMarkerCircle) circle.style.transform = "scale(1)";
    });

    const marker = new mapLib.Marker({ element: el })
      .setLngLat([pin.lng, pin.lat])
      .addTo(map);

    el.addEventListener("click", (e) => {
      e.stopPropagation();
      setActiveMarker(circle);
      openBusinessPanel(pin.id, pinIndexMap.get(`${pin.lat}:${pin.lng}`) ?? -1, pin.lat, pin.lng);
    });

    // Store circle on marker so navigateToPin can highlight it
    marker._circle = circle;
    currentMarkers.push(marker);
  });


  document.getElementById("loading").classList.add("hidden");
}

// ──────────────────────────────────────────────────────────
// Business detail panel
// ──────────────────────────────────────────────────────────

async function openBusinessPanel(businessId, pinIndex, clickedLat, clickedLng) {
  const panel = document.getElementById("info-panel");
  const body = document.getElementById("panel-body");
  const meta = document.getElementById("panel-meta");

  if (pinIndex !== undefined) {
    currentPinIndex = pinIndex;
  }

  // Show loading state
  document.getElementById("panel-name").textContent = "Loading\u2026";
  body.innerHTML = "";
  meta.innerHTML = "";
  panel.classList.add("open");
  updatePanelNav();

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
      sortMentions(biz.mentions).forEach(mention => {
        const card = document.createElement("div");
        card.className = "mention-card";

        // Sentiment badge on the mention
        const sentimentBadge = mention.sentiment
          ? `<span class="badge badge-sentiment-${mention.sentiment}" style="font-size:11px; margin-bottom:8px; display:inline-block;">${sentimentEmoji(mention.sentiment)} ${capitalise(mention.sentiment)}</span>`
          : "";

        // Quotes
        const quotesHtml = (mention.quotes || [])
          .map(q => `<div class="quote" ${quoteColorStyle(mention.sentiment)}>"${escapeHtml(q)}"</div>`)
          .join("");

        // Timestamp link
        const timeLabel = mention.timestamp_seconds
          ? ` (${formatTime(mention.timestamp_seconds)})`
          : "";

        card.innerHTML = `
          ${sentimentBadge}
          <div class="video-title">${escapeHtml(mention.video_title)}</div>
          ${quotesHtml || `<div class="quote" style="opacity:0.5">No direct quotes extracted.</div>`}
          <button class="watch-link" data-yt-url="${mention.youtube_url}" onclick="toggleYtEmbed(this)">▶ Watch on YouTube${timeLabel}</button>
        `;
        body.appendChild(card);
      });
    }

    // Address + street view (for the clicked location only)
    const addressEl = document.getElementById("panel-address");
    const activeLoc = biz.locations && biz.locations.find(loc =>
      clickedLat != null && Math.abs(loc.lat - clickedLat) < 0.0001
        && Math.abs(loc.lng - clickedLng) < 0.0001
    ) || (biz.locations && biz.locations[0]) || null;

    if (activeLoc) {
      const svHtml = (activeLoc.lat && activeLoc.lng)
        ? ` <a href="https://www.google.com/maps?q=&layer=c&cbll=${activeLoc.lat},${activeLoc.lng}" target="_blank" rel="noopener" class="street-view-link">📍 Street View</a>`
        : "";
      addressEl.innerHTML = `<div class="address-row">${escapeHtml(activeLoc.address)}${svHtml}</div>`;
    } else {
      addressEl.innerHTML = "";
    }

  } catch (err) {
    body.innerHTML = `<p style="color:#f44336;padding:16px 0;font-size:13px;">Failed to load business details.</p>`;
    console.error(err);
  }
}

function setActiveMarker(circle) {
  // Deactivate previous
  if (activeMarkerCircle && activeMarkerCircle !== circle) {
    activeMarkerCircle.style.transform = "scale(1)";
    activeMarkerCircle.style.boxShadow = "0 2px 6px rgba(0,0,0,0.4)";
    activeMarkerCircle.style.border = "2px solid #fff";
    activeMarkerCircle.style.zIndex = "";
  }
  activeMarkerCircle = circle;
  if (circle) {
    circle.style.transform = "scale(1.5)";
    circle.style.boxShadow = "0 0 0 3px #fff, 0 2px 8px rgba(0,0,0,0.6)";
    circle.style.border = "2px solid #fff";
    circle.style.zIndex = "1";
  }
}

function closePanel() {
  document.getElementById("info-panel").classList.remove("open");
  currentPinIndex = -1;
  setActiveMarker(null);
}

function updatePanelNav() {
  const total = visiblePins.length;
  const nav = document.getElementById("panel-nav");
  const counter = document.getElementById("panel-nav-counter");
  const prevBtn = document.getElementById("panel-prev");
  const nextBtn = document.getElementById("panel-next");

  if (total < 2 || currentPinIndex < 0) {
    nav.style.display = "none";
    return;
  }

  nav.style.display = "flex";
  counter.textContent = `${currentPinIndex + 1} / ${total}`;
  prevBtn.disabled = false;
  nextBtn.disabled = false;
}

function navigateToPin(index) {
  const total = visiblePins.length;
  if (!total) return;
  const wrapped = ((index % total) + total) % total;
  const pin = visiblePins[wrapped];
  // Highlight the marker for this pin
  const marker = currentMarkers.find(m => {
    const ll = m.getLngLat();
    return ll.lng === pin.lng && ll.lat === pin.lat;
  });
  setActiveMarker(marker ? marker._circle : null);
  openBusinessPanel(pin.id, wrapped, pin.lat, pin.lng);
  map.easeTo({ center: [pin.lng, pin.lat], duration: 300 });
}

document.getElementById("panel-prev").addEventListener("click", () => navigateToPin(currentPinIndex - 1));
document.getElementById("panel-next").addEventListener("click", () => navigateToPin(currentPinIndex + 1));

// ──────────────────────────────────────────────────────────
// Filter handlers
// ──────────────────────────────────────────────────────────

document.getElementById("filter-city").addEventListener("change", e => {
  activeFilters.city = e.target.value;
  const city = citiesById[activeFilters.city];
  if (city && city.is_virtual) {
    loadListView();
  } else {
    loadMapData(); // fitMapToPins() is called inside after markers are placed
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
  if (isListViewActive()) { renderListView(); } else { renderMap(allPins); renderUnlocatedStrip(); }
});

// Search — client-side, no server reload needed
let _searchTimer = null;
document.getElementById("filter-search").addEventListener("input", e => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    activeFilters.search = e.target.value.trim();
    if (isListViewActive()) { renderListView(); } else { renderMap(allPins); renderUnlocatedStrip(); }
  }, 200);
});

// Date preset buttons
document.querySelectorAll(".date-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const preset = btn.dataset.preset;
    const customRange = document.getElementById("date-custom-range");
    if (activeFilters.datePreset === preset) {
      // deselect
      activeFilters.datePreset = "";
      activeFilters.dateFrom = "";
      activeFilters.dateTo = "";
      btn.classList.remove("active");
      customRange.style.display = "none";
    } else {
      document.querySelectorAll(".date-btn").forEach(b => b.classList.remove("active"));
      activeFilters.datePreset = preset;
      btn.classList.add("active");
      customRange.style.display = preset === "custom" ? "flex" : "none";
      if (preset !== "custom") {
        activeFilters.dateFrom = "";
        activeFilters.dateTo = "";
      }
    }
    if (preset !== "custom" || activeFilters.datePreset === "") {
      if (isListViewActive()) { loadListView(); } else { loadMapData(); }
    }
  });
});

// Custom date range inputs
document.getElementById("date-from").addEventListener("change", e => {
  activeFilters.dateFrom = e.target.value;
  if (isListViewActive()) { loadListView(); } else { loadMapData(); }
});
document.getElementById("date-to").addEventListener("change", e => {
  activeFilters.dateTo = e.target.value;
  if (isListViewActive()) { loadListView(); } else { loadMapData(); }
});

function isListViewActive() {
  return document.getElementById("list-view").style.display !== "none";
}

document.getElementById("panel-close").addEventListener("click", closePanel);

// Swipe-down-to-close on mobile (attached to header so it doesn't
// conflict with scrolling the mentions list in panel-body)
(function () {
  const header = document.getElementById("info-panel").querySelector(".info-panel-header");
  let touchStartY = 0;
  let touchStartX = 0;

  header.addEventListener("touchstart", (e) => {
    touchStartY = e.touches[0].clientY;
    touchStartX = e.touches[0].clientX;
  }, { passive: true });

  header.addEventListener("touchend", (e) => {
    const dy = e.changedTouches[0].clientY - touchStartY;
    const dx = Math.abs(e.changedTouches[0].clientX - touchStartX);
    // Close if swipe is downward (>50px), more vertical than horizontal,
    // and the panel is currently open
    if (dy > 50 && dy > dx * 1.5 && document.getElementById("info-panel").classList.contains("open")) {
      closePanel();
    }
  }, { passive: true });
})();

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
