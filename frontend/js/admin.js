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
  await Promise.all([loadStats(), loadCities()]);
  setupTabs();
  loadReviewQueue();
  loadVideos();
  loadBusinesses();
  loadSeedStatus();
}

let citiesList = [];

async function loadCities() {
  try {
    citiesList = await apiFetch("/api/cities");
  } catch (e) {
    console.error("Failed to load cities", e);
  }
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
        ? `<span class="error-badge" data-error="${esc(v.error_message)}">⚠ Error<div class="error-tooltip">${esc(v.error_message)}</div></span>`
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
        <td style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick="reprocessVideo(${v.id})">↻ Reprocess</button>
          ${v.mention_count > 0 ? `<button class="btn btn-danger btn-sm" onclick="clearExtractions(${v.id}, this)">✕ Clear</button>` : ""}
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

async function clearExtractions(videoId, btn) {
  if (!confirm("Delete all mentions and businesses from this video? Orphaned businesses (no other mentions) will also be removed. The video will be reset to pending.")) return;
  btn.disabled = true;
  try {
    const result = await apiFetch(`/api/admin/videos/${videoId}/extractions`, { method: "DELETE" });
    toast(`Cleared: ${result.mentions_deleted} mention(s), ${result.businesses_deleted} business(es) deleted`, "success");
    loadVideos();
    loadStats();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
    btn.disabled = false;
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
    bizDataMap.clear();
    businesses.forEach(b => bizDataMap.set(b.id, b));
    renderBizRows();
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state" style="color:var(--color-negative);">Error loading businesses.</td></tr>`;
    console.error(e);
  }
}

function renderBizRows() {
  const tbody = document.getElementById("biz-table-body");
  const businesses = Array.from(bizDataMap.values());

  if (!businesses.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No businesses found.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  businesses.forEach(b => {
    const isMergeSource = mergeSourceId === b.id;
    const inMergeMode = mergeSourceId !== null;

    const tr = document.createElement("tr");
    if (isMergeSource) tr.style.opacity = "0.5";

    let actionBtns = "";
    if (inMergeMode) {
      if (!isMergeSource) {
        actionBtns = `<button class="btn btn-primary btn-sm" onclick="confirmMerge(${b.id})">⇄ Merge here</button>`;
      }
    } else {
      actionBtns = `
        <button class="btn btn-secondary btn-sm" onclick="openEditModal(${b.id})">Edit</button>
        ${b.review_status !== "approved" ? `<button class="btn btn-success btn-sm" onclick="quickApprove(${b.id})">✓ Approve</button>` : ""}
        <button class="btn btn-secondary btn-sm" onclick="startMerge(${b.id})" title="Merge this business into another">⇄ Merge</button>
      `;
    }

    tr.innerHTML = `
      <td><strong>${esc(b.name)}</strong>${b.pending_review_count > 0 ? ` <span class="chip chip-pending_review">${b.pending_review_count} review</span>` : ""}</td>
      <td>${esc(b.city_name)}</td>
      <td>${b.category ? esc(b.category) : "–"}</td>
      <td><span class="chip chip-${b.review_status}">${b.review_status}</span></td>
      <td>${b.mention_count}</td>
      <td>${b.is_closed ? "🔒 Closed" : "–"}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap;">${actionBtns}</td>
    `;
    tbody.appendChild(tr);
  });
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

// ──────────────────────────────────────────────────────────
// Merge mode
// ──────────────────────────────────────────────────────────

let mergeSourceId = null; // business selected as the one to be absorbed

function startMerge(id) {
  mergeSourceId = id;
  const biz = bizDataMap.get(id);
  const banner = document.getElementById("merge-banner");
  document.getElementById("merge-banner-text").textContent =
    ` "${biz.name}" will be absorbed — now click "Merge here" on the business to keep.`;
  banner.style.display = "flex";
  // Re-render rows to show Merge-here buttons
  renderBizRows();
}

function cancelMerge() {
  mergeSourceId = null;
  document.getElementById("merge-banner").style.display = "none";
  renderBizRows();
}

async function confirmMerge(keepId) {
  const source = bizDataMap.get(mergeSourceId);
  const target = bizDataMap.get(keepId);
  if (!source || !target) return;

  const ok = confirm(
    `Merge "${source.name}" INTO "${target.name}"?\n\n` +
    `• All ${source.mention_count} mention(s) from "${source.name}" will move to "${target.name}"\n` +
    `• Addresses will be combined (duplicates removed)\n` +
    `• "${source.name}" will be deleted\n\n` +
    `This cannot be undone.`
  );
  if (!ok) return;

  try {
    await apiFetch("/api/admin/businesses/merge", {
      method: "POST",
      body: JSON.stringify({ keep_id: keepId, merge_ids: [mergeSourceId] }),
    });
    toast(`Merged "${source.name}" into "${target.name}"`, "success");
    mergeSourceId = null;
    document.getElementById("merge-banner").style.display = "none";
    loadBusinesses();
    loadStats();
  } catch (e) {
    toast(`Merge failed: ${e.message}`, "error");
  }
}

// Edit modal
let editBizData = null;
const bizDataMap = new Map(); // keyed by business id — avoids embedding JSON in onclick attrs

const SENTIMENT_LABELS = {
  positive: "👍 Positive",
  negative: "👎 Negative",
  neutral:  "😐 Neutral",
  mixed:    "🤔 Mixed",
};

async function openEditModal(id) {
  editBizData = bizDataMap.get(id);
  if (!editBizData) return;
  document.getElementById("edit-biz-id").value = id;
  document.getElementById("edit-biz-name").value = editBizData.name || "";

  // Populate city dropdown
  const citySelect = document.getElementById("edit-biz-city");
  citySelect.innerHTML = citiesList.map(c =>
    `<option value="${c.id}" ${c.id == editBizData.city_id ? "selected" : ""}>${esc(c.name)}</option>`
  ).join("");
  document.getElementById("edit-biz-category").value = editBizData.category || "other";
  document.getElementById("edit-biz-review-status").value = editBizData.review_status || "pending_review";
  // Populate addresses: primary first, then extras
  const allAddresses = [];
  if (editBizData.address) allAddresses.push(editBizData.address);
  if (editBizData.extra_addresses) allAddresses.push(...editBizData.extra_addresses);
  const addrContainer = document.getElementById("edit-biz-addresses");
  addrContainer.innerHTML = "";
  (allAddresses.length ? allAddresses : [""]).forEach(a => addAddressRow(a));
  document.getElementById("edit-biz-notes").value = editBizData.admin_notes || "";
  document.getElementById("edit-biz-closed").checked = !!editBizData.is_closed;
  document.getElementById("edit-modal").style.display = "flex";

  // Load mentions for vibe editing
  const mentionsList = document.getElementById("edit-mentions-list");
  mentionsList.innerHTML = `<span style="font-size:13px;color:var(--color-text-muted);">Loading…</span>`;
  try {
    const mentions = await apiFetch(`/api/admin/businesses/${id}/mentions`);
    renderMentions(mentions);
  } catch (e) {
    mentionsList.innerHTML = `<span style="font-size:13px;color:var(--color-negative);">Failed to load mentions.</span>`;
  }
}

function renderMentions(mentions) {
  const list = document.getElementById("edit-mentions-list");
  if (!mentions.length) {
    list.innerHTML = `<span style="font-size:13px;color:var(--color-text-muted);">No mentions yet.</span>`;
    return;
  }

  list.innerHTML = "";
  mentions.forEach(m => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;flex-direction:column;gap:8px;padding:12px;background:var(--color-surface-2);border:1px solid var(--color-border);border-radius:var(--radius);";

    const timeLabel = m.timestamp_seconds ? ` · ${formatTime(m.timestamp_seconds)}` : "";
    const title = m.video_title.length > 60 ? m.video_title.slice(0, 60) + "…" : m.video_title;

    // Build quote rows HTML
    const quotesHtml = (m.quotes.length ? m.quotes : [""]).map((q, i) => `
      <div class="quote-row" style="display:flex;gap:6px;align-items:flex-start;">
        <textarea rows="2" data-quote-idx="${i}"
          style="flex:1;padding:6px 8px;background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius);color:var(--color-text);font-size:12px;resize:vertical;line-height:1.5;">${esc(q)}</textarea>
        <button class="btn btn-danger btn-sm" style="margin-top:2px;" onclick="removeQuote(this)">✕</button>
      </div>
    `).join("");

    row.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
        <a href="${m.youtube_url}" target="_blank" style="font-size:12px;color:var(--color-accent);text-decoration:none;flex:1;min-width:0;"
           title="${esc(m.video_title)}">▶ ${esc(title)}${timeLabel}</a>
        <div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
          <select id="mention-sentiment-${m.id}"
            style="padding:4px 8px;background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius);color:var(--color-text);font-size:12px;">
            <option value="">— no vibe —</option>
            ${Object.entries(SENTIMENT_LABELS).map(([v, l]) =>
              `<option value="${v}" ${m.sentiment === v ? "selected" : ""}>${l}</option>`
            ).join("")}
          </select>
        </div>
      </div>
      <div style="font-size:11px;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:0.5px;">Quotes</div>
      <div class="quotes-container" id="quotes-${m.id}" style="display:flex;flex-direction:column;gap:6px;">
        ${quotesHtml}
      </div>
      <div style="display:flex;gap:6px;justify-content:flex-end;">
        <button class="btn btn-secondary btn-sm" onclick="addQuote(${m.id})">+ Add quote</button>
        <button class="btn btn-primary btn-sm" onclick="saveMention(${m.id})">Save</button>
      </div>
    `;
    list.appendChild(row);
  });
}

function addAddressRow(value = "") {
  const container = document.getElementById("edit-biz-addresses");
  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:6px;align-items:center;";
  row.innerHTML = `
    <input type="text" value="${esc(value)}" placeholder="e.g. 123 Main St, Vancouver, BC"
      style="flex:1;padding:8px;background:var(--color-surface-2);border:1px solid var(--color-border);border-radius:var(--radius);color:var(--color-text);font-size:13px;" />
    <button type="button" class="btn btn-danger btn-sm" onclick="this.closest('div').remove()">✕</button>
  `;
  container.appendChild(row);
  if (!value) row.querySelector("input").focus();
}

function addQuote(mentionId) {
  const container = document.getElementById(`quotes-${mentionId}`);
  const idx = container.querySelectorAll(".quote-row").length;
  const div = document.createElement("div");
  div.className = "quote-row";
  div.style.cssText = "display:flex;gap:6px;align-items:flex-start;";
  div.innerHTML = `
    <textarea rows="2" data-quote-idx="${idx}"
      style="flex:1;padding:6px 8px;background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius);color:var(--color-text);font-size:12px;resize:vertical;line-height:1.5;"></textarea>
    <button class="btn btn-danger btn-sm" style="margin-top:2px;" onclick="removeQuote(this)">✕</button>
  `;
  container.appendChild(div);
  div.querySelector("textarea").focus();
}

function removeQuote(btn) {
  btn.closest(".quote-row").remove();
}

async function saveMention(mentionId) {
  const sentiment = document.getElementById(`mention-sentiment-${mentionId}`).value || null;
  const container = document.getElementById(`quotes-${mentionId}`);
  const quotes = Array.from(container.querySelectorAll("textarea"))
    .map(t => t.value.trim())
    .filter(Boolean);

  try {
    await apiFetch(`/api/admin/mentions/${mentionId}`, {
      method: "PUT",
      body: JSON.stringify({ sentiment, quotes }),
    });
    toast("Mention saved", "success");
    loadBusinesses();
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

document.getElementById("edit-cancel").addEventListener("click", () => {
  document.getElementById("edit-modal").style.display = "none";
});

document.getElementById("edit-save").addEventListener("click", async () => {
  const id = document.getElementById("edit-biz-id").value;
  const allAddrs = Array.from(document.getElementById("edit-biz-addresses").querySelectorAll("input"))
    .map(i => i.value.trim()).filter(Boolean);
  const payload = {
    name: document.getElementById("edit-biz-name").value.trim(),
    city_id: parseInt(document.getElementById("edit-biz-city").value) || null,
    category: document.getElementById("edit-biz-category").value,
    review_status: document.getElementById("edit-biz-review-status").value,
    address: allAddrs[0] || null,
    extra_addresses: allAddrs.slice(1),
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
