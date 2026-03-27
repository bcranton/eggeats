/* =========================================================
   Egg Eats — Admin JS
   ========================================================= */

const API = "";

// ──────────────────────────────────────────────────────────
// Auth check
// ──────────────────────────────────────────────────────────

async function checkAuth() {
  try {
    const me = await apiFetch("/auth/me");
    document.getElementById("admin-email").textContent = me.email;
    document.getElementById("login-screen").style.display = "none";
    document.getElementById("main-content").style.display = "block";
    init();
  } catch {
    document.getElementById("login-screen").style.display = "flex";
    document.getElementById("main-content").style.display = "none";
    // Hide header actions when not logged in
    document.getElementById("btn-logout").style.display = "none";
  }
}

document.getElementById("btn-logout").addEventListener("click", async () => {
  await apiFetch("/auth/logout", { method: "POST" });
  window.location.href = "/admin.html";
});

// ──────────────────────────────────────────────────────────
// Init
// ──────────────────────────────────────────────────────────

async function init() {
  await loadStats();
  setupTabs();
  loadReviewQueue();
  loadVideos();
  loadBusinesses();
  loadSeedStatus();
}

// ──────────────────────────────────────────────────────────
// Stats
// ──────────────────────────────────────────────────────────

async function loadStats() {
  try {
    const s = await apiFetch("/api/admin/stats");
    document.getElementById("st-total-videos").textContent = s.total_videos;
    document.getElementById("st-pending-videos").textContent = s.pending_videos;
    document.getElementById("st-completed-videos").textContent = s.completed_videos;
    document.getElementById("st-failed-videos").textContent = s.failed_videos;
    document.getElementById("st-total-biz").textContent = s.total_businesses;
    document.getElementById("st-approved-biz").textContent = s.approved_businesses;
    document.getElementById("st-review-queue").textContent = s.pending_review_queue;
    document.getElementById("st-mentions").textContent = s.total_mentions;
  } catch (e) {
    console.error("Failed to load stats", e);
  }
}

// ──────────────────────────────────────────────────────────
// Tabs
// ──────────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });
}

// ──────────────────────────────────────────────────────────
// Review Queue
// ──────────────────────────────────────────────────────────

async function loadReviewQueue() {
  const status = document.getElementById("review-status-filter").value;
  const list = document.getElementById("review-list");
  list.innerHTML = `<div class="empty-state"><span class="spinner"></span> Loading…</div>`;

  try {
    const items = await apiFetch(`/api/admin/review-queue?status=${status}`);
    if (!items.length) {
      list.innerHTML = `<div class="empty-state">No items with status "${status}".</div>`;
      return;
    }

    list.innerHTML = "";
    items.forEach(item => {
      const card = document.createElement("div");
      card.className = "review-card";
      card.dataset.id = item.id;

      const ytLink = `<a href="${item.youtube_url}" target="_blank" style="color:var(--color-accent);font-size:12px;">▶ Watch${item.timestamp_seconds ? ` at ${formatTime(item.timestamp_seconds)}` : ""}</a>`;

      card.innerHTML = `
        <div class="review-card-header">
          <div>
            <div class="review-card-title">
              Raw: "<strong>${esc(item.raw_business_name)}</strong>"
              → Guessed: "<strong>${esc(item.canonical_business_name)}</strong>"
            </div>
            <div class="review-card-subtitle">
              ${esc(item.video_title)} &bull; Confidence: ${item.confidence_score ? (item.confidence_score * 100).toFixed(0) + "%" : "unknown"}
              &bull; ${ytLink}
            </div>
          </div>
          <span class="chip chip-${item.status}">${item.status}</span>
        </div>
        <div class="review-reason">⚠ ${esc(item.reason)}</div>
        ${item.transcript_excerpt ? `<div class="transcript-excerpt">${esc(item.transcript_excerpt)}</div>` : ""}
        ${item.status === "pending" ? `
          <div class="review-actions">
            <input type="text" id="correction-${item.id}" placeholder="Corrected name (if wrong)…" value="${esc(item.suggested_correction || "")}" />
            <button class="btn btn-success btn-sm" onclick="resolveItem(${item.id}, 'approve')">✓ Approve</button>
            <button class="btn btn-primary btn-sm" onclick="resolveItem(${item.id}, 'correct')">✎ Correct Name</button>
            <button class="btn btn-danger btn-sm" onclick="resolveItem(${item.id}, 'dismiss')">✕ Dismiss</button>
          </div>
        ` : `<div style="font-size:12px;color:var(--color-text-muted);">
          ${item.suggested_correction ? `Corrected to: <strong>${esc(item.suggested_correction)}</strong>` : ""}
        </div>`}
      `;
      list.appendChild(card);
    });
  } catch (e) {
    list.innerHTML = `<div class="empty-state" style="color:var(--color-negative);">Error loading review queue.</div>`;
    console.error(e);
  }
}

async function resolveItem(itemId, action) {
  const correctionInput = document.getElementById(`correction-${itemId}`);
  const correctedName = correctionInput ? correctionInput.value.trim() : "";

  if (action === "correct" && !correctedName) {
    toast("Enter a corrected name first", "error");
    correctionInput?.focus();
    return;
  }

  try {
    await apiFetch(`/api/admin/review-queue/${itemId}`, {
      method: "PUT",
      body: JSON.stringify({ action, corrected_name: correctedName || null }),
    });
    toast(`Item ${action}d successfully`, "success");
    loadReviewQueue();
    loadStats();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

document.getElementById("review-status-filter").addEventListener("change", loadReviewQueue);

// ──────────────────────────────────────────────────────────
// Videos
// ──────────────────────────────────────────────────────────

async function loadVideos() {
  const tbody = document.getElementById("videos-table-body");
  tbody.innerHTML = `<tr><td colspan="6" class="empty-state"><span class="spinner"></span> Loading…</td></tr>`;

  try {
    const videos = await apiFetch("/api/admin/videos");
    if (!videos.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No videos found.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    videos.forEach(v => {
      const tr = document.createElement("tr");
      const publishedDate = v.published_at
        ? new Date(v.published_at).toLocaleDateString()
        : "–";
      const errorHtml = v.error_message
        ? `<span title="${esc(v.error_message)}" style="color:var(--color-negative);cursor:help;">⚠ Error</span>`
        : "–";

      tr.innerHTML = `
        <td>
          <a href="https://youtube.com/watch?v=${v.youtube_video_id}" target="_blank"
             style="color:var(--color-accent);text-decoration:none;font-size:13px;" class="truncate" title="${esc(v.title)}">
            ${esc(v.title.length > 55 ? v.title.slice(0, 55) + "…" : v.title)}
          </a>
        </td>
        <td style="white-space:nowrap;">${publishedDate}</td>
        <td><span class="chip chip-${v.processing_status}">${v.processing_status}</span></td>
        <td>${v.mention_count}</td>
        <td>${errorHtml}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="reprocessVideo(${v.id})">↻ Reprocess</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state" style="color:var(--color-negative);">Error loading videos.</td></tr>`;
    console.error(e);
  }
}

async function reprocessVideo(videoId) {
  try {
    await apiFetch(`/api/admin/videos/${videoId}/reprocess`, { method: "POST" });
    toast("Video queued for reprocessing", "success");
    loadVideos();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

document.getElementById("btn-refresh-videos").addEventListener("click", loadVideos);

let pipelinePoller = null;

function startPipelinePolling() {
  const statusEl = document.getElementById("pipeline-status");
  statusEl.style.display = "block";
  statusEl.innerHTML = `<span class="spinner"></span> Pipeline running… (auto-refreshing every 15s — <button class="btn btn-secondary btn-sm" onclick="stopPipelinePolling()">Stop</button>)`;

  if (pipelinePoller) clearInterval(pipelinePoller);
  pipelinePoller = setInterval(() => {
    loadVideos();
    loadStats();
  }, 15000);
}

function stopPipelinePolling() {
  if (pipelinePoller) {
    clearInterval(pipelinePoller);
    pipelinePoller = null;
  }
  const statusEl = document.getElementById("pipeline-status");
  statusEl.style.display = "none";
}

document.getElementById("btn-run-pipeline").addEventListener("click", async () => {
  const btn = document.getElementById("btn-run-pipeline");
  btn.disabled = true;

  try {
    await apiFetch("/api/admin/pipeline/run", {
      method: "POST",
      body: JSON.stringify({ only_new: true }),
    });
    toast("Pipeline started. Videos tab will auto-refresh every 15s.", "success");
    startPipelinePolling();
  } catch (e) {
    toast(`Failed to start pipeline: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
});

// ──────────────────────────────────────────────────────────
// Businesses
// ──────────────────────────────────────────────────────────

async function loadBusinesses() {
  const tbody = document.getElementById("biz-table-body");
  tbody.innerHTML = `<tr><td colspan="7" class="empty-state"><span class="spinner"></span> Loading…</td></tr>`;

  const status = document.getElementById("biz-status-filter").value;
  const qs = status ? `?review_status=${status}` : "";

  try {
    const businesses = await apiFetch(`/api/admin/businesses${qs}`);
    if (!businesses.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No businesses found.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    bizDataMap.clear();
    businesses.forEach(b => {
      bizDataMap.set(b.id, b);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${esc(b.name)}</strong>${b.pending_review_count > 0 ? ` <span class="chip chip-pending_review">${b.pending_review_count} review</span>` : ""}</td>
        <td>${esc(b.city_name)}</td>
        <td>${b.category ? esc(b.category) : "–"}</td>
        <td><span class="chip chip-${b.review_status}">${b.review_status}</span></td>
        <td>${b.mention_count}</td>
        <td>${b.is_closed ? "🔒 Closed" : "–"}</td>
        <td style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="openEditModal(${b.id})">Edit</button>
          ${b.review_status !== "approved" ? `<button class="btn btn-success btn-sm" onclick="quickApprove(${b.id})">✓ Approve</button>` : ""}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state" style="color:var(--color-negative);">Error loading businesses.</td></tr>`;
    console.error(e);
  }
}

async function quickApprove(bizId) {
  try {
    await apiFetch(`/api/admin/businesses/${bizId}`, {
      method: "PUT",
      body: JSON.stringify({ review_status: "approved" }),
    });
    toast("Business approved", "success");
    loadBusinesses();
    loadStats();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

document.getElementById("biz-status-filter").addEventListener("change", loadBusinesses);

// Edit modal
let editBizData = null;
const bizDataMap = new Map(); // keyed by business id — avoids embedding JSON in onclick attrs

function openEditModal(id) {
  editBizData = bizDataMap.get(id);
  if (!editBizData) return;
  document.getElementById("edit-biz-id").value = id;
  document.getElementById("edit-biz-name").value = editBizData.name || "";
  document.getElementById("edit-biz-category").value = editBizData.category || "other";
  document.getElementById("edit-biz-review-status").value = editBizData.review_status || "pending_review";
  document.getElementById("edit-biz-notes").value = editBizData.admin_notes || "";
  document.getElementById("edit-biz-closed").checked = !!editBizData.is_closed;
  document.getElementById("edit-modal").style.display = "flex";
}

document.getElementById("edit-cancel").addEventListener("click", () => {
  document.getElementById("edit-modal").style.display = "none";
});

document.getElementById("edit-save").addEventListener("click", async () => {
  const id = document.getElementById("edit-biz-id").value;
  const payload = {
    name: document.getElementById("edit-biz-name").value.trim(),
    category: document.getElementById("edit-biz-category").value,
    review_status: document.getElementById("edit-biz-review-status").value,
    admin_notes: document.getElementById("edit-biz-notes").value.trim() || null,
    is_closed: document.getElementById("edit-biz-closed").checked,
  };

  try {
    await apiFetch(`/api/admin/businesses/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    toast("Business updated", "success");
    document.getElementById("edit-modal").style.display = "none";
    loadBusinesses();
    loadStats();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
});

// Close modal on backdrop click
document.getElementById("edit-modal").addEventListener("click", e => {
  if (e.target === document.getElementById("edit-modal")) {
    document.getElementById("edit-modal").style.display = "none";
  }
});

// ──────────────────────────────────────────────────────────
// Utilities
// ──────────────────────────────────────────────────────────

async function apiFetch(path, options = {}) {
  const defaults = {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
  };
  const res = await fetch(`${API}${path}`, { ...defaults, ...options });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json().catch(() => ({}));
}

function toast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const t = document.createElement("div");
  t.className = `toast ${type}`;
  t.textContent = message;
  container.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function esc(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ──────────────────────────────────────────────────────────
// Setup / Seed
// ──────────────────────────────────────────────────────────

async function loadSeedStatus() {
  const box = document.getElementById("seed-status-box");
  if (!box) return;
  try {
    const s = await apiFetch("/api/admin/seed/status");
    if (s.cities.length === 0) {
      box.innerHTML = `<span style="color:var(--color-warning);">⚠ No cities seeded yet. Use the form below to seed the database before running the pipeline.</span>`;
    } else {
      const cityList = s.cities.map(c => `<strong>${esc(c.name)}</strong> (${esc(c.country)})`).join(", ");
      const plList = s.playlists.map(p => `<strong>${esc(p.name)}</strong> <span style="color:var(--color-text-muted);">[${esc(p.youtube_playlist_id)}]</span>`).join(", ");
      box.innerHTML = `
        <div style="display:flex;flex-direction:column;gap:6px;">
          <div>✓ Cities: ${cityList}</div>
          <div>✓ Playlists: ${plList || "<em>none</em>"}</div>
        </div>`;
    }
  } catch (e) {
    box.innerHTML = `<span style="color:var(--color-negative);">Error loading seed status.</span>`;
  }
}

document.getElementById("btn-seed").addEventListener("click", async () => {
  const btn = document.getElementById("btn-seed");
  btn.disabled = true;
  try {
    const result = await apiFetch("/api/admin/seed", {
      method: "POST",
      body: JSON.stringify({
        city_name: document.getElementById("seed-city-name").value.trim(),
        country: document.getElementById("seed-country").value.trim(),
        search_keywords: document.getElementById("seed-keywords").value.trim(),
        playlist_youtube_id: document.getElementById("seed-playlist-id").value.trim(),
        playlist_name: document.getElementById("seed-playlist-name").value.trim(),
      }),
    });
    const cityMsg = result.city.created ? `Created city "${result.city.name}"` : `City "${result.city.name}" already exists`;
    const plMsg = result.playlist.created ? `Created playlist "${result.playlist.name}"` : `Playlist "${result.playlist.name}" already exists`;
    toast(`${cityMsg}. ${plMsg}.`, "success");
    loadSeedStatus();
  } catch (e) {
    toast(`Seed failed: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
  }
});

// ── Start ──────────────────────────────────────────────────
checkAuth();
