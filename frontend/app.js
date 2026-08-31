"use strict";
/**
 * Cloud IDE — Frontend
 * Single-page app, zero dependencies, vanilla JS.
 */

/* ── State ─────────────────────────────────────────────────────────────── */
const S = {
  workspaces: [],
  view: "workspaces", // "workspaces" | "deleted"
};

/* ── DOM shortcuts ──────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const Q = sel => document.querySelector(sel);
const QA = sel => document.querySelectorAll(sel);

/* ── Refs ─────────────────────────────────────────────────────────────── */
const R = {
  landing:          $("landing"),
  dashboard:        $("dashboard"),
  sidebar:          $("sidebar"),
  menuToggle:       $("menu-toggle"),
  apiDot:           $("api-dot"),
  apiLabel:         $("api-label"),
  refreshBtn:       $("refresh-btn"),
  openCreateModal:  $("open-create-modal"),
  emptyCBtn:        $("empty-create-btn"),
  tabTitle:         $("tab-title"),
  tabSubtitle:      $("tab-subtitle"),
  // Stats
  statTotal:   $("stat-total"),
  statRunning: $("stat-running"),
  statStopped: $("stat-stopped"),
  statDeleted: $("stat-deleted"),
  // Grids
  wsGrid:    $("ws-grid"),
  delGrid:   $("del-grid"),
  wsEmpty:   $("ws-empty"),
  delEmpty:  $("del-empty"),
  wsTab:     $("tab-workspaces"),
  delTab:    $("tab-deleted"),
  // Sidebar badge
  delBadge:  $("sidebar-deleted-badge"),
  // Toasts
  toasts:    $("toasts"),
  // Create modal
  createModal:    $("create-modal"),
  createForm:     $("create-form"),
  cUserId:        $("c-user-id"),
  cPassword:      $("c-password"),
  pwToggle:       $("pw-toggle"),
  pwEye:          $("pw-eye"),
  pwStrengthBar:  $("pw-strength-bar"),
  modalSubmit:    $("modal-submit"),
  modalCancel:    $("modal-cancel"),
  modalClose:     $("modal-close"),
  createPreview:  $("create-preview"),
  previewUrl:     $("preview-url"),
  step1:          $("step-1-dot"),
  step2:          $("step-2-dot"),
  step3:          $("step-3-dot"),
  createSuccess:  $("create-success"),
  successUrl:     $("success-url"),
  successOpenBtn: $("success-open-btn"),
  successCloseBtn:$("success-close-btn"),
  // Confirm modal
  confirmModal:  $("confirm-modal"),
  confirmTitle:  $("confirm-title"),
  confirmDesc:   $("confirm-desc"),
  confirmOk:     $("confirm-ok"),
  confirmCancel: $("confirm-cancel"),
  // Landing
  landingGoDash:     $("landing-go-dashboard"),
  heroForm:          $("hero-form"),
  heroUserId:        $("hero-user-id"),
  heroPassword:      $("hero-password"),
  heroCreateBtn:     $("hero-create-btn"),
};

/* ── API helper ─────────────────────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res  = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await res.text();
  let body = null;
  if (text) { try { body = JSON.parse(text); } catch { body = { detail: text }; } }
  if (!res.ok) throw new Error(body?.detail || `Error ${res.status}`);
  return body;
}

/* ── Toast ──────────────────────────────────────────────────────────────── */
function toast(msg, type = "info", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast toast--${type}`;
  el.innerHTML = `<span class="toast-dot"></span><span class="toast-msg">${esc(msg)}</span>`;
  R.toasts.prepend(el);
  setTimeout(() => el.remove(), ms);
}

/* ── Confirm dialog ─────────────────────────────────────────────────────── */
function showConfirm(title, desc) {
  return new Promise(resolve => {
    R.confirmTitle.textContent = title;
    R.confirmDesc.textContent  = desc;
    R.confirmModal.hidden      = false;
    R.confirmModal.removeAttribute("aria-hidden");

    const done = v => {
      R.confirmModal.hidden = true;
      R.confirmModal.setAttribute("aria-hidden", "true");
      resolve(v);
    };
    R.confirmOk.onclick     = () => done(true);
    R.confirmCancel.onclick = () => done(false);
    const onKey = e => { if (e.key === "Escape") { done(false); document.removeEventListener("keydown", onKey); } };
    document.addEventListener("keydown", onKey);
  });
}

/* ── Utils ──────────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function relTime(iso) {
  const d = (Date.now() - new Date(iso)) / 1000;
  if (d < 60)  return `${~~d}s ago`;
  if (d < 3600) return `${~~(d/60)}m ago`;
  if (d < 86400) return `${~~(d/3600)}h ago`;
  return new Intl.DateTimeFormat(undefined,{dateStyle:"medium"}).format(new Date(iso));
}
function btnLoad(btn, label = "Working…") {
  btn.disabled = true;
  btn._orig = btn.innerHTML;
  btn.innerHTML = `<span class="spinner"></span> ${esc(label)}`;
}
function btnReset(btn) {
  btn.disabled = false;
  if (btn._orig) { btn.innerHTML = btn._orig; delete btn._orig; }
}

/* ── Routing ────────────────────────────────────────────────────────────── */
function showDashboard() {
  R.landing.classList.add("hidden");
  R.dashboard.classList.remove("hidden");
}
function showLanding() {
  R.dashboard.classList.add("hidden");
  R.landing.classList.remove("hidden");
}

function switchTab(tab) {
  S.view = tab;
  QA(".sidebar-nav-item").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  R.wsTab.classList.toggle("active",  tab === "workspaces");
  R.delTab.classList.toggle("active", tab === "deleted");

  if (tab === "workspaces") {
    R.tabTitle.textContent    = "Workspaces";
    R.tabSubtitle.textContent = "Your active coding environments";
  } else {
    R.tabTitle.textContent    = "Deleted workspaces";
    R.tabSubtitle.textContent = "Files are kept — restore or purge permanently";
  }
}

/* ── Stats & API status ─────────────────────────────────────────────────── */
function updateStats(online) {
  const ws = S.workspaces;
  const total   = ws.length;
  const running = ws.filter(w => w.status === "running").length;
  const stopped = ws.filter(w => w.status === "stopped").length;
  const deleted = ws.filter(w => w.status === "deleted").length;

  R.statTotal.textContent   = total;
  R.statRunning.textContent = running;
  R.statStopped.textContent = stopped;
  R.statDeleted.textContent = deleted;

  if (deleted > 0) {
    R.delBadge.textContent = deleted;
    R.delBadge.hidden = false;
  } else {
    R.delBadge.hidden = true;
  }

  if (online !== undefined) {
    R.apiDot.className  = `api-dot ${online ? "api-dot--on" : "api-dot--off"}`;
    R.apiLabel.textContent = online ? "API online" : "API offline";
  }
}

/* ── Build a workspace card ─────────────────────────────────────────────── */
function buildCard(ws) {
  const el = document.createElement("article");
  el.className = `ws-card ws-card--${ws.status}`;

  const letter = (ws.user_id || "?")[0].toUpperCase();

  const urlContent = ws.url
    ? `<span class="card-url-text">${esc(ws.url)}</span>
       <div class="card-url-btns">
         <button class="btn-ghost btn-xs" onclick="doCopy('${esc(ws.id)}')" title="Copy URL">
           <svg style="width:12px;height:12px" viewBox="0 0 20 20" fill="currentColor"><path d="M8 3a1 1 0 011-1h2a1 1 0 110 2H9a1 1 0 01-1-1z"/><path d="M6 3a2 2 0 00-2 2v11a2 2 0 002 2h8a2 2 0 002-2V5a2 2 0 00-2-2 3 3 0 01-3 3H9a3 3 0 01-3-3z"/></svg>
         </button>
         <button class="btn-primary btn-xs" onclick="doOpen('${esc(ws.id)}')">
           <svg style="width:11px;height:11px" viewBox="0 0 20 20" fill="currentColor"><path d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"/></svg>
           Open IDE
         </button>
       </div>`
    : `<span class="card-url-text card-url-text--na">${ws.status === "deleted" ? "Deleted — restore to get URL" : "Starting…"}</span>`;

  let actions = "";
  if (ws.status === "running") {
    actions = `
      <button class="btn-amber btn-sm" onclick="doStop('${esc(ws.id)}')">⏸ Stop</button>
      <button class="btn-ghost btn-sm" onclick="doHeartbeat('${esc(ws.id)}')">♥ Ping</button>
      <button class="btn-danger btn-sm" onclick="doDelete('${esc(ws.id)}')">Delete</button>`;
  } else if (ws.status === "stopped") {
    actions = `
      <button class="btn-success btn-sm" onclick="doStart('${esc(ws.id)}')">▶ Start</button>
      <button class="btn-danger btn-sm" onclick="doDelete('${esc(ws.id)}')">Delete</button>`;
  } else {
    actions = `
      <button class="btn-success btn-sm" onclick="doStart('${esc(ws.id)}')">↺ Restore</button>
      <button class="btn-danger btn-sm" onclick="doPurge('${esc(ws.id)}')">🗑 Purge</button>`;
  }

  el.innerHTML = `
    <div class="card-top">
      <div style="display:flex;align-items:center;gap:12px;min-width:0">
        <div class="card-avatar card-avatar--${ws.status}">${esc(letter)}</div>
        <div class="card-info">
          <div class="card-name">${esc(ws.user_id)}</div>
          <div class="card-id">${esc(ws.id)}</div>
        </div>
      </div>
      <span class="status-badge status-badge--${ws.status}">${esc(ws.status)}</span>
    </div>
    <div class="card-meta">
      <div class="card-meta-item">
        <div class="card-meta-lbl">Created</div>
        <div class="card-meta-val">${relTime(ws.created_at)}</div>
      </div>
      <div class="card-meta-item">
        <div class="card-meta-lbl">Last active</div>
        <div class="card-meta-val">${relTime(ws.last_active)}</div>
      </div>
    </div>
    <div class="card-url">${urlContent}</div>
    <div class="card-actions">${actions}</div>
  `;
  return el;
}

/* ── Render ─────────────────────────────────────────────────────────────── */
function render() {
  const active  = S.workspaces.filter(w => w.status !== "deleted");
  const deleted = S.workspaces.filter(w => w.status === "deleted");

  R.wsGrid.innerHTML  = "";
  R.delGrid.innerHTML = "";

  if (active.length === 0) {
    R.wsEmpty.hidden = false;
  } else {
    R.wsEmpty.hidden = true;
    active.forEach(w => R.wsGrid.appendChild(buildCard(w)));
  }

  if (deleted.length === 0) {
    R.delEmpty.hidden = false;
  } else {
    R.delEmpty.hidden = true;
    deleted.forEach(w => R.delGrid.appendChild(buildCard(w)));
  }
}

/* ── Load workspaces ────────────────────────────────────────────────────── */
async function loadWorkspaces(silent = false) {
  if (!silent) {
    R.refreshBtn.classList.add("spinning");
    R.refreshBtn.disabled = true;
  }
  try {
    const [health, workspaces] = await Promise.all([
      api("/health"),
      api("/api/workspaces"),
    ]);
    S.workspaces = workspaces || [];
    updateStats(health?.ok === true);
    render();

    // Auto-show dashboard if user has workspaces
    if (S.workspaces.length > 0) showDashboard();
  } catch (err) {
    updateStats(false);
    if (!silent) toast(`Could not load workspaces: ${err.message}`, "error");
  } finally {
    if (!silent) {
      R.refreshBtn.classList.remove("spinning");
      R.refreshBtn.disabled = false;
    }
  }
}

/* ── Workspace actions (exposed globally for inline onclick) ────────────── */
window.doOpen = id => {
  const ws = S.workspaces.find(w => w.id === id);
  if (ws?.url) window.open(ws.url, "_blank", "noopener,noreferrer");
};

window.doCopy = async id => {
  const ws = S.workspaces.find(w => w.id === id);
  if (!ws?.url) return;
  try {
    await navigator.clipboard.writeText(ws.url);
    toast("URL copied!", "success", 2500);
  } catch { toast("Clipboard not available.", "error"); }
};

window.doStop = async id => {
  try {
    await api(`/api/workspaces/${id}/stop`, { method: "POST" });
    toast("Workspace stopped.", "success");
    await loadWorkspaces(true);
  } catch (e) { toast(`Stop failed: ${e.message}`, "error"); }
};

window.doStart = async id => {
  try {
    await api(`/api/workspaces/${id}/start`, { method: "POST" });
    toast("Workspace started.", "success");
    await loadWorkspaces(true);
  } catch (e) { toast(`Start failed: ${e.message}`, "error"); }
};

window.doHeartbeat = async id => {
  try {
    await api(`/api/workspaces/${id}/heartbeat`, { method: "POST" });
    toast("Idle timer reset.", "info", 2500);
    await loadWorkspaces(true);
  } catch (e) { toast(`Ping failed: ${e.message}`, "error"); }
};

window.doDelete = async id => {
  const ok = await showConfirm(
    "Delete workspace",
    "The container will be removed but your files are kept. You can restore and re-launch later."
  );
  if (!ok) return;
  try {
    await api(`/api/workspaces/${id}`, { method: "DELETE" });
    toast("Workspace deleted. Files preserved.", "info");
    await loadWorkspaces(true);
  } catch (e) { toast(`Delete failed: ${e.message}`, "error"); }
};

window.doPurge = async id => {
  const ok = await showConfirm(
    "Purge permanently",
    "⚠️ This will delete the container AND all stored files. This cannot be undone."
  );
  if (!ok) return;
  try {
    await api(`/api/workspaces/${id}?purge=true`, { method: "DELETE" });
    toast("Workspace purged.", "info");
    await loadWorkspaces(true);
  } catch (e) { toast(`Purge failed: ${e.message}`, "error"); }
};

/* ── Create modal ────────────────────────────────────────────────────────── */
function openCreateModal(prefillName = "") {
  R.createForm.hidden    = false;
  R.createSuccess.hidden = true;
  R.cUserId.value        = prefillName;
  R.cPassword.value      = "";
  R.createPreview.hidden = true;
  R.pwStrengthBar.style.width      = "0";
  R.pwStrengthBar.style.background = "";
  setStep(1);
  R.createModal.hidden = false;
  R.createModal.removeAttribute("aria-hidden");
  setTimeout(() => R.cUserId.focus(), 60);
}

function closeCreateModal() {
  R.createModal.hidden = true;
  R.createModal.setAttribute("aria-hidden", "true");
}

function setStep(n) {
  [R.step1, R.step2, R.step3].forEach((s, i) => {
    s.classList.toggle("active", i + 1 === n);
    s.classList.toggle("done",   i + 1 < n);
  });
}

// Password strength
R.cPassword?.addEventListener("input", () => {
  const v = R.cPassword.value;
  const len = v.length;
  let score = 0;
  if (len >= 6)  score++;
  if (len >= 10) score++;
  if (/[A-Z]/.test(v)) score++;
  if (/[0-9]/.test(v)) score++;
  if (/[^A-Za-z0-9]/.test(v)) score++;
  const pct  = Math.min((score / 5) * 100, 100);
  const clrs = ["#ef4444","#f59e0b","#f59e0b","#10b981","#10b981"];
  R.pwStrengthBar.style.width      = pct + "%";
  R.pwStrengthBar.style.background = clrs[score - 1] || "#ef4444";

  // update step
  const nameOk = /^[a-zA-Z0-9_.\-]+$/.test(R.cUserId.value.trim()) && R.cUserId.value.trim().length > 0;
  setStep(nameOk ? (len >= 6 ? 3 : 2) : 1);

  // show preview
  if (nameOk && len >= 1) {
    R.createPreview.hidden = false;
    R.previewUrl.textContent = `/ws/…/ (after creation)`;
  }
});

R.cUserId?.addEventListener("input", () => {
  const nameOk = /^[a-zA-Z0-9_.\-]+$/.test(R.cUserId.value.trim()) && R.cUserId.value.trim().length > 0;
  const pwOk   = R.cPassword.value.length >= 6;
  setStep(nameOk ? (pwOk ? 3 : 2) : 1);
  R.createPreview.hidden = !nameOk;
});

// Show/hide password
R.pwToggle?.addEventListener("click", () => {
  const show = R.cPassword.type === "password";
  R.cPassword.type = show ? "text" : "password";
  R.pwEye.innerHTML = show
    ? `<path fill-rule="evenodd" d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074l-1.78-1.781zm4.261 4.26l1.514 1.515a2.003 2.003 0 012.45 2.45l1.514 1.515a4 4 0 00-5.478-5.48z" clip-rule="evenodd"/><path d="M12.454 16.697L9.75 13.992a4 4 0 01-3.742-3.741L2.335 6.578A9.98 9.98 0 00.458 10c1.274 4.057 5.065 7 9.542 7 .847 0 1.669-.105 2.454-.303z"/>`
    : `<path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/><path fill-rule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clip-rule="evenodd"/>`;
});

/* ── Create workspace (shared) ──────────────────────────────────────────── */
async function createWorkspace(userId, password, submitBtn) {
  const name = userId.trim();
  const pw   = password.trim();

  if (!name) { toast("Enter a workspace name.", "error"); return null; }
  if (!/^[a-zA-Z0-9_.\-]+$/.test(name)) { toast("Name has invalid characters.", "error"); return null; }
  if (pw.length < 6) { toast("Password must be at least 6 characters.", "error"); return null; }

  if (submitBtn) btnLoad(submitBtn, "Launching…");
  try {
    const ws = await api("/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ user_id: name, password: pw }),
    });
    await loadWorkspaces(true);
    return ws;
  } catch (e) {
    toast(`Create failed: ${e.message}`, "error");
    return null;
  } finally {
    if (submitBtn) btnReset(submitBtn);
  }
}

/* Create form submit */
R.createForm?.addEventListener("submit", async e => {
  e.preventDefault();
  setStep(3);
  const ws = await createWorkspace(R.cUserId.value, R.cPassword.value, R.modalSubmit);
  if (!ws) return;

  // Show success screen
  R.createForm.hidden    = true;
  R.createSuccess.hidden = false;
  const url = ws.url || "#";
  R.successUrl.href        = url;
  R.successUrl.textContent = url;
  R.successOpenBtn.href    = url;

  toast(`Workspace "${ws.user_id}" created!`, "success");
  showDashboard();
});

R.successCloseBtn?.addEventListener("click", closeCreateModal);
R.modalClose?.addEventListener("click", closeCreateModal);
R.modalCancel?.addEventListener("click", closeCreateModal);
R.createModal?.addEventListener("click", e => { if (e.target === R.createModal) closeCreateModal(); });

/* Open modal buttons */
R.openCreateModal?.addEventListener("click", () => openCreateModal());
R.emptyCBtn?.addEventListener("click",       () => openCreateModal());

/* ── Hero (landing) form ────────────────────────────────────────────────── */
R.heroCreateBtn?.addEventListener("click", async () => {
  const ws = await createWorkspace(R.heroUserId.value, R.heroPassword.value, R.heroCreateBtn);
  if (!ws) return;

  // Show success in modal
  R.heroUserId.value   = "";
  R.heroPassword.value = "";
  openCreateModal();
  R.createForm.hidden    = true;
  R.createSuccess.hidden = false;
  const url = ws.url || "#";
  R.successUrl.href        = url;
  R.successUrl.textContent = url;
  R.successOpenBtn.href    = url;
  showDashboard();
  toast(`Workspace "${ws.user_id}" is launching!`, "success");
});

R.landingGoDash?.addEventListener("click", showDashboard);

/* ── Sidebar nav ────────────────────────────────────────────────────────── */
QA(".sidebar-nav-item").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

/* ── Mobile sidebar ──────────────────────────────────────────────────────── */
R.menuToggle?.addEventListener("click", () => R.sidebar.classList.toggle("open"));
document.addEventListener("click", e => {
  if (R.sidebar.classList.contains("open")
      && !R.sidebar.contains(e.target)
      && e.target !== R.menuToggle) {
    R.sidebar.classList.remove("open");
  }
});

/* ── Refresh ─────────────────────────────────────────────────────────────── */
R.refreshBtn?.addEventListener("click", () => loadWorkspaces(false));

/* ── Keyboard ────────────────────────────────────────────────────────────── */
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (!R.createModal.hidden)  closeCreateModal();
    if (!R.confirmModal.hidden) { R.confirmModal.hidden = true; R.confirmModal.setAttribute("aria-hidden","true"); }
  }
});

/* ── Auto-refresh every 15s ──────────────────────────────────────────────── */
setInterval(() => loadWorkspaces(true), 15_000);

/* ── Boot ────────────────────────────────────────────────────────────────── */
(async () => {
  await loadWorkspaces(false);
  // If no workspaces, stay on landing; otherwise show dashboard
  if (S.workspaces.length === 0) showLanding();
  else showDashboard();
})();
