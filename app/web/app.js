const state = {
  channels: [],
  lists: [],
  selectedListId: null,
  allEvents: [],
  lastPlatesByChannelId: {},
};
let eventSource = null;
let streamReconnectTimer = null;
let debugLogSource = null;
let debugLogReconnectTimer = null;
let lastDebugLogId = 0;
let debugSettingsCache = null;
function api(path) {
  return `${document.getElementById("apiBase").value.trim()}${path}`;
}
async function jfetch(url, method = "GET", body = null) {
  const r = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.status === 204 ? null : r.json();
}
function flagByCountry(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  return normalized
    ? `/web/images/flags/${normalized}.png`
    : "/web/images/flags/eu.png";
}
function flagHtml(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  const src = flagByCountry(normalized || "eu");
  const fallback = flagByCountry("eu");
  return `<img class='ev-flag' src='${src}' alt='${normalized || "unknown"}' onerror="this.onerror=null;this.src='${fallback}'" />`;
}
function switchTab(name) {
  document
    .querySelectorAll(".ttab")
    .forEach((el) => el.classList.toggle("active", el.dataset.tab === name));
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  updateTopbarTitle();
  if (name === "obs") scheduleVideoGridLayout();
}
function switchSettings(name) {
  document
    .querySelectorAll(".snav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.sp === name));
  document
    .querySelectorAll(".settings-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`sp-${name}`).classList.add("active");
  updateTopbarTitle();
}
function getActiveTabName() {
  return document.querySelector(".ttab.active")?.dataset.tab || "obs";
}

function getActiveSettingsName() {
  return document.querySelector(".snav-item.active")?.dataset.sp || "general";
}

function updateTopbarTitle() {
  const titleNode = document.querySelector(".topbar-title");
  if (!titleNode) return;
  const tabLabels = {
    obs: "Наблюдение",
    journal: "Журнал",
    lists: "Списки",
    settings: "Настройки",
  };
  const settingsLabels = {
    general: "Общие",
    channels: "Каналы",
    controllers: "Контроллеры",
    debug: "Debug",
  };
  const activeTab = getActiveTabName();
  if (activeTab !== "settings") {
    titleNode.textContent = tabLabels[activeTab] || tabLabels.obs;
    return;
  }
  const activeSettings = getActiveSettingsName();
  titleNode.textContent = `${tabLabels.settings} / ${settingsLabels[activeSettings] || settingsLabels.general}`;
}
function switchChannelSettingsTab(name) {
  document
    .querySelectorAll(".ch-tab")
    .forEach((el) => el.classList.toggle("active", el.dataset.chTab === name));
  document
    .querySelectorAll(".ch-group")
    .forEach((el) => (el.style.display = "none"));
  const active = document.getElementById(`ch-group-${name}`);
  if (active) {
    active.style.display = "block";
  }
}

function syncChannelConfigVisibility() {
  const pane = document.getElementById("channelConfigPane");
  const empty = document.getElementById("channelConfigEmpty");
  const hasSelectedChannel = Boolean(selectedChannelId);
  if (pane) pane.style.display = hasSelectedChannel ? "block" : "none";
  if (empty) empty.style.display = hasSelectedChannel ? "none" : "flex";
}

function syncControllerConfigVisibility() {
  const pane = document.getElementById("controllerConfigPane");
  const empty = document.getElementById("controllerConfigEmpty");
  const hasSelectedController = Boolean(selectedControllerId);
  if (pane) pane.style.display = hasSelectedController ? "block" : "none";
  if (empty) empty.style.display = hasSelectedController ? "none" : "flex";
}


async function refreshSystemResources() {
  try {
    const resources = await jfetch(api("/api/system/resources"));
    document.getElementById("cpuStat").textContent =
      `${Math.round(Number(resources.cpu_percent) || 0)}%`;
    document.getElementById("ramStat").textContent =
      `${Math.round(Number(resources.ram_percent) || 0)}%`;
  } catch (_e) {}
}

async function refreshChannels() {
  state.channels = await jfetch(api("/api/channels"));
  renderVideoGrid();
  renderChannelsList();
  fillChannelFilter();
}
function gridConfig(v) {
  if (v === "1x1") return [1, 1];
  if (v === "2x3") return [2, 3];
  if (v === "3x3") return [3, 3];
  return [2, 2];
}
function statusTextForChannel(ch) {
  const running = (ch.metrics || {}).state === "running";
  const lastError = (ch.metrics || {}).last_error;
  return !running
    ? "Канал остановлен"
    : lastError
      ? `Ошибка: ${lastError}`
      : "Ожидание кадра...";
}

function buildNoSignalHtml(statusText) {
  return `
    <div class="cam-no-signal">
      <img class="cam-no-signal-icon" src="/web/assets/icons/nosignal.svg" alt="" />
      <p>${statusText}</p>
    </div>
  `;
}

function getCellPreviewSignal(cell, ch) {
  const metricReady = Boolean((ch.metrics || {}).preview_ready);
  const imageReady = cell?.dataset.previewLoaded === "1";
  return metricReady || imageReady;
}

function ensureNoSignalOverlay(cell) {
  if (!cell) return null;
  let overlay = cell.querySelector(".cam-no-signal");
  if (overlay) return overlay;
  const preview = cell.querySelector(".cam-preview");
  if (!preview) return null;
  preview.insertAdjacentHTML("afterend", buildNoSignalHtml("Ожидание кадра..."));
  return cell.querySelector(".cam-no-signal");
}

function setNoSignalVisibility(cell, shouldShow, statusText) {
  const overlay = ensureNoSignalOverlay(cell);
  if (!overlay) return;
  const textNode = overlay.querySelector("p");
  if (textNode && statusText) textNode.textContent = statusText;
  const hidden = overlay.dataset.hidden === "1";
  if (shouldShow === !hidden) return;
  overlay.dataset.hidden = shouldShow ? "0" : "1";
  overlay.style.display = shouldShow ? "flex" : "none";
}

function bindPreviewLifecycle(cell, img) {
  if (!cell || !img || img.dataset.lifecycleBound === "1") return;
  img.dataset.lifecycleBound = "1";
  img.addEventListener("load", () => {
    cell.dataset.previewLoaded = "1";
    setNoSignalVisibility(cell, false, cell.dataset.statusText || "");
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.add("live");
      statusDot.classList.remove("off");
    }
  });
  img.addEventListener("error", () => {
    cell.dataset.previewLoaded = "0";
    setNoSignalVisibility(cell, true, cell.dataset.statusText || "Ожидание кадра...");
    const statusDot = cell.querySelector(".cam-status");
    if (statusDot) {
      statusDot.classList.remove("live");
      statusDot.classList.add("off");
    }
  });
}

function ensurePreviewStream(img, channelId) {
  if (!img) return;
  const url = api(`/api/channels/${channelId}/preview.mjpg`);
  if (img.dataset.url !== url) {
    const cell = img.closest(".video-cell");
    if (cell) {
      cell.dataset.previewLoaded = "0";
      setNoSignalVisibility(cell, true, cell.dataset.statusText || "Ожидание кадра...");
    }
    img.dataset.url = url;
    img.src = url;
  }
}

function createVideoCell(ch, idx) {
  const statusText = statusTextForChannel(ch);
  const cell = document.createElement("div");
  cell.className = `video-cell ${idx === 0 ? "active" : ""}`;
  cell.dataset.channelId = String(ch.id);
  cell.dataset.previewLoaded = "0";
  cell.dataset.statusText = statusText;
  cell.innerHTML = `<div class='video-cell-bg'></div><img class='cam-preview' id='v-${ch.id}' alt='preview CAM-${ch.id}' /><div class='cam-label'>${ch.name}</div><div class='cam-status off'></div><div class='cam-plate' id='plate-${ch.id}'></div>`;
  const preview = cell.querySelector(".cam-preview");
  bindPreviewLifecycle(cell, preview);
  ensureNoSignalOverlay(cell);
  const hasPreviewSignal = getCellPreviewSignal(cell, ch);
  setNoSignalVisibility(cell, !hasPreviewSignal, statusText);
  const statusDot = cell.querySelector(".cam-status");
  if (statusDot) {
    statusDot.classList.toggle("live", hasPreviewSignal);
    statusDot.classList.toggle("off", !hasPreviewSignal);
  }
  ensurePreviewStream(preview, ch.id);
  updateChannelLastPlate(ch.id, state.lastPlatesByChannelId[ch.id]);
  return cell;
}

function updateVideoCell(cell, ch, idx) {
  const statusText = statusTextForChannel(ch);
  cell.dataset.statusText = statusText;
  cell.classList.toggle("active", idx === 0);
  const label = cell.querySelector(".cam-label");
  if (label) label.textContent = ch.name;
  const hasPreviewSignal = getCellPreviewSignal(cell, ch);
  const statusDot = cell.querySelector(".cam-status");
  if (statusDot) {
    statusDot.classList.toggle("live", hasPreviewSignal);
    statusDot.classList.toggle("off", !hasPreviewSignal);
  }
  setNoSignalVisibility(cell, !hasPreviewSignal, statusText);
  const preview = cell.querySelector(".cam-preview");
  bindPreviewLifecycle(cell, preview);
  ensurePreviewStream(preview, ch.id);
  updateChannelLastPlate(ch.id, state.lastPlatesByChannelId[ch.id]);
}

function computeVideoGridRowHeight(grid, rows, cols) {
  if (!grid || rows <= 0 || cols <= 0) return null;
  const style = window.getComputedStyle(grid);
  const gap = Number.parseFloat(style.rowGap || style.gap || "0") || 0;
  const width = grid.clientWidth;
  const height = grid.clientHeight;
  if (width <= 0 || height <= 0) return null;

  const availableWidth = width - gap * (cols - 1);
  const availableHeight = height - gap * (rows - 1);
  if (availableWidth <= 0 || availableHeight <= 0) return null;

  const byWidth = (availableWidth / cols) * (9 / 16);
  const byHeight = availableHeight / rows;
  const rowHeight = Math.floor(Math.min(byWidth, byHeight));
  return rowHeight > 0 ? rowHeight : null;
}

function renderVideoGrid() {
  const grid = document.getElementById("videoGrid");
  const [rows, cols] = gridConfig(document.getElementById("gridSelect").value);
  grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  const stableRowHeight = computeVideoGridRowHeight(grid, rows, cols);
  grid.style.gridTemplateRows = stableRowHeight
    ? `repeat(${rows}, ${stableRowHeight}px)`
    : `repeat(${rows}, minmax(0, 1fr))`;
  const visible = state.channels.slice(0, rows * cols);
  document.getElementById("channelsCount").textContent =
    `${state.channels.length} канала`;

  const visibleIds = new Set(visible.map((ch) => String(ch.id)));
  Array.from(grid.children).forEach((cell) => {
    if (!visibleIds.has(cell.dataset.channelId || "")) {
      cell.remove();
    }
  });

  for (const [idx, ch] of visible.entries()) {
    let cell = grid.querySelector(`.video-cell[data-channel-id='${ch.id}']`);
    if (!cell) {
      cell = createVideoCell(ch, idx);
    } else {
      updateVideoCell(cell, ch, idx);
    }
    grid.appendChild(cell);
  }
}

let videoGridLayoutFrame = null;
let videoGridResizeObserver = null;
function scheduleVideoGridLayout() {
  if (videoGridLayoutFrame !== null) return;
  videoGridLayoutFrame = requestAnimationFrame(() => {
    videoGridLayoutFrame = null;
    const obsTab = document.getElementById("tab-obs");
    if (!obsTab || !obsTab.classList.contains("active")) return;
    renderVideoGrid();
  });
}

function setupVideoGridLayoutGuards() {
  window.addEventListener("resize", scheduleVideoGridLayout);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleVideoGridLayout();
  });
  if (typeof ResizeObserver !== "function") return;
  const obsLeft = document.querySelector("#tab-obs .obs-left");
  if (!obsLeft) return;
  videoGridResizeObserver = new ResizeObserver(() => {
    scheduleVideoGridLayout();
  });
  videoGridResizeObserver.observe(obsLeft);
}


function resolveChannelIdFromEvent(ev) {
  const directId = Number(ev.channel_id);
  if (Number.isFinite(directId) && directId > 0) return directId;
  const byName = state.channels.find((c) => String(c.name) === String(ev.channel));
  return byName ? Number(byName.id) : null;
}

function updateChannelLastPlate(channelId, plateData) {
  const id = Number(channelId);
  if (!Number.isFinite(id) || id <= 0) return;
  const plateNode = document.getElementById(`plate-${id}`);
  if (!plateNode) return;
  const plateText = String((plateData || {}).plate || "").trim();
  plateNode.textContent = plateText;
  plateNode.style.display = plateText ? "block" : "none";
}

function applyLastPlate(ev) {
  const channelId = resolveChannelIdFromEvent(ev);
  if (!channelId) return;
  const payload = {
    plate: ev.plate || "",
    timestamp: ev.timestamp || null,
    country: ev.country || null,
    confidence: ev.confidence ?? null,
    direction: ev.direction || null,
  };
  state.lastPlatesByChannelId[channelId] = payload;
  updateChannelLastPlate(channelId, payload);
}

async function hydrateChannelLastPlates() {
  const rows = await jfetch(api('/api/channels/last-plates'));
  state.lastPlatesByChannelId = rows || {};
  Object.entries(state.lastPlatesByChannelId).forEach(([channelId, payload]) => {
    updateChannelLastPlate(Number(channelId), payload);
  });
}

function renderEventFeed() {
  const feed = document.getElementById("eventFeed");
  if (!feed) return;
  feed.innerHTML = "";
  const events = state.allEvents;
  for (const [i, item] of events.entries()) {
    const conf = Number(item.confidence || 0);
    const direction = formatDirection(item.direction);
    const div = document.createElement("div");
    div.className = `ev-item ${i === 0 ? "hot" : ""}`;
    div.setAttribute("role", "button");
    div.setAttribute("tabindex", "0");
    div.innerHTML = `${flagHtml(item.country)}<div class='ev-body'><div class='ev-plate'>${item.plate || "—"}</div><div class='ev-meta'>${item.channel || `CAM-${item.channel_id || ""}`} · <span>${new Date(item.timestamp || Date.now()).toLocaleTimeString()}</span> · <span class='badge ${direction.badgeClass}'>${direction.label}</span></div></div><div class='ev-conf ${conf < 0.85 ? "warn" : ""}'>${conf.toFixed(2)}</div>`;
    div.onclick = () => openEventDetails(item);
    div.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openEventDetails(item);
      }
    };
    feed.appendChild(div);

    if (feed.scrollHeight > feed.clientHeight) {
      feed.removeChild(div);
      if (feed.children.length === 0) {
        feed.appendChild(div);
      }
      break;
    }
  }
}

function pushEvent(ev) {
  applyLastPlate(ev);
  state.allEvents.unshift(ev);
  if (state.allEvents.length > 500) state.allEvents.pop();
  renderEventFeed();
  renderJournal();
  addDebug(
    `[INFO] event: ${ev.plate || "-"} conf=${Number(ev.confidence || 0).toFixed(2)}`,
    "ok",
  );
}
async function loadJournal() {
  state.allEvents = await jfetch(api("/api/events?limit=500"));
  renderEventFeed();
  renderJournal();
}
function renderJournal() {
  const needle = (
    document.getElementById("fltPlate").value || ""
  ).toUpperCase();
  const chan = document.getElementById("fltChannel").value;
  const rows = state.allEvents.filter(
    (e) =>
      (!needle ||
        String(e.plate || "")
          .toUpperCase()
          .includes(needle)) &&
      (!chan || String(e.channel || e.channel_id || "") === chan),
  );
  const body = document.getElementById("journalBody");
  body.innerHTML = "";
  rows.forEach((ev) => {
    const conf = Number(ev.confidence || 0);
    const direction = formatDirection(ev.direction);
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${new Date(ev.timestamp).toLocaleTimeString()}</td><td>${ev.channel || `CAM-${ev.channel_id || ""}`}</td><td>${flagHtml(ev.country)} ${ev.country || ""}</td><td><span class='badge ${direction.badgeClass}'>${direction.label}</span></td><td class='plate-cell'>${ev.plate || ""}</td><td class='conf-cell' style='color:${conf < 0.85 ? "var(--warning)" : "var(--success)"}'>${conf.toFixed(2)}</td><td>${ev.source || ""}</td>`;
    tr.onclick = () => openEventDetails(ev);
    body.appendChild(tr);
  });
}

function formatDirection(directionValue) {
  const normalized = String(directionValue || "").toUpperCase();
  const isApproaching =
    normalized === "IN" ||
    normalized === "APPROACHING" ||
    normalized === "APPROACH";
  const isReceding =
    normalized === "OUT" ||
    normalized === "RECEDING" ||
    normalized === "RECEDE";

  if (isApproaching) {
    return {
      badgeClass: "badge-in",
      label: "→ Приближение",
      plain: "Приближение",
    };
  }

  if (isReceding) {
    return {
      badgeClass: "badge-out",
      label: "← Отдаление",
      plain: "Отдаление",
    };
  }

  return {
    badgeClass: "badge-out",
    label: "—",
    plain: "—",
  };
}

async function loadLists() {
  state.lists = await jfetch(api("/api/lists"));
  renderLists();
  renderCustomListOptions(currentChannelCustomListIds);
}
function renderLists() {
  const items = document.getElementById("listItems");
  items.innerHTML = "";
  state.lists.forEach((l, idx) => {
    const div = document.createElement("div");
    div.className = `list-item ${l.id === state.selectedListId || (!state.selectedListId && idx === 0) ? "active" : ""}`;
    if (!state.selectedListId && idx === 0) state.selectedListId = l.id;
    div.innerHTML = `<div class='list-item-dot ${l.type === "white" ? "dot-white" : "dot-black"}'></div><div class='list-item-name'>${l.name}</div><div class='list-item-count'>…</div>`;
    div.onclick = () => {
      state.selectedListId = l.id;
      renderLists();
      loadEntries(l.id);
    };
    items.appendChild(div);
  });
  if (state.selectedListId) loadEntries(state.selectedListId);
}
async function loadEntries(listId) {
  const rows = await jfetch(api(`/api/lists/${listId}/entries`));
  const list = state.lists.find((x) => x.id === listId);
  document.getElementById("listTitle").textContent = list ? list.name : "—";
  const b = document.getElementById("listTypeBadge");
  b.textContent = list?.type === "black" ? "Черный список" : "Белый список";
  b.className = `type-badge ${list?.type === "black" ? "type-black" : "type-white"}`;
  const body = document.getElementById("entriesBody");
  body.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class='plate-cell'>${r.plate}</td><td>${r.comment || ""}</td>`;
    body.appendChild(tr);
  });
}

let selectedChannelId = null;
let channelConfigRequestToken = 0;
let controllersCache = [];
let selectedControllerId = null;
let roiPoints = [];
let currentChannelCustomListIds = [];
const hotkeyMap = new Map();
let roiDrag = -1;
let roiBgImage = null;

function val(id) {
  return document.getElementById(id).value;
}
function setVal(id, v) {
  document.getElementById(id).value = v ?? "";
}
function setChk(id, v) {
  document.getElementById(id).checked = !!v;
}
function parseIds(raw) {
  return String(raw || "")
    .split(",")
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isFinite(x));
}

function applyTheme(theme) {
  const normalized = String(theme || "dark").toLowerCase() === "light" ? "light" : "dark";
  document.body.setAttribute("data-theme", normalized);
  try {
    localStorage.setItem("anpr_theme", normalized);
  } catch (_e) {}
}

async function loadGlobalSettings() {
  const g = await jfetch(api("/api/settings"));
  setVal("g_grid", g.grid);
  setVal("g_theme", g.theme);
  applyTheme(g.theme);
  setChk("g_sl_enabled", g.reconnect.signal_loss.enabled);
  setVal("g_frame_timeout", g.reconnect.signal_loss.frame_timeout_seconds);
  setVal("g_retry_interval", g.reconnect.signal_loss.retry_interval_seconds);
  setChk("g_periodic_enabled", g.reconnect.periodic.enabled);
  setVal("g_periodic_minutes", g.reconnect.periodic.interval_minutes);
  setVal("g_screenshots_dir", g.storage.screenshots_dir);
  setVal("g_logs_dir", g.storage.logs_dir);
  setChk("g_auto_cleanup", g.storage.auto_cleanup_enabled);
  setVal("g_cleanup_minutes", g.storage.cleanup_interval_minutes);
  setVal("g_events_retention", g.storage.events_retention_days);
  setVal("g_media_retention", g.storage.media_retention_days);
  setVal("g_max_screenshots", g.storage.max_screenshots_mb);
  setVal("g_export_dir", g.storage.export_dir);
  setVal("g_postgres_dsn", g.storage.postgres_dsn);
  setVal("g_log_level", g.logging.level);
  setVal("g_log_retention", g.logging.retention_days);
  setVal("g_timezone", g.time.timezone);
  setVal("g_offset_minutes", g.time.offset_minutes);
  setVal("g_plates_dir", g.plates.config_dir);
  setVal("g_countries", (g.plates.enabled_countries || []).join(","));
  setChk("d_boxes", g.debug.show_detection_boxes);
  setChk("d_ocr", g.debug.show_ocr_text);
  setChk("d_tracks", g.debug.show_direction_tracks);
  setChk("d_metrics", g.debug.show_channel_metrics);
  setChk("d_log", g.debug.log_panel_enabled);
  debugSettingsCache = g.debug || {};
  applyDebugPanelVisibility();
}

async function saveGeneral() {
  applyTheme(val("g_theme"));
  const payload = {
    grid: val("g_grid"),
    theme: val("g_theme"),
    reconnect: {
      signal_loss: {
        enabled: document.getElementById("g_sl_enabled").checked,
        frame_timeout_seconds: Number(val("g_frame_timeout")),
        retry_interval_seconds: Number(val("g_retry_interval")),
      },
      periodic: {
        enabled: document.getElementById("g_periodic_enabled").checked,
        interval_minutes: Number(val("g_periodic_minutes")),
      },
    },
    storage: {
      screenshots_dir: val("g_screenshots_dir"),
      logs_dir: val("g_logs_dir"),
      auto_cleanup_enabled: document.getElementById("g_auto_cleanup").checked,
      cleanup_interval_minutes: Number(val("g_cleanup_minutes")),
      events_retention_days: Number(val("g_events_retention")),
      media_retention_days: Number(val("g_media_retention")),
      max_screenshots_mb: Number(val("g_max_screenshots")),
      export_dir: val("g_export_dir"),
      postgres_dsn: val("g_postgres_dsn"),
    },
    logging: {
      level: val("g_log_level"),
      retention_days: Number(val("g_log_retention")),
    },
    time: {
      timezone: val("g_timezone"),
      offset_minutes: Number(val("g_offset_minutes")),
    },
    plates: {
      config_dir: val("g_plates_dir"),
      enabled_countries: parseIds("").length
        ? []
        : String(val("g_countries"))
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean),
    },
    debug: {
      show_detection_boxes: document.getElementById("d_boxes").checked,
      show_ocr_text: document.getElementById("d_ocr").checked,
      show_direction_tracks: document.getElementById("d_tracks").checked,
      show_channel_metrics: document.getElementById("d_metrics").checked,
      log_panel_enabled: document.getElementById("d_log").checked,
    },
  };
  const updated = await jfetch(api("/api/settings"), "PUT", payload);
  debugSettingsCache = (updated || {}).debug || payload.debug;
  applyDebugPanelVisibility();
  addDebug("[OK] global settings saved", "ok");
}

function renderChannelsList() {
  const box = document.getElementById("channelsList");
  box.innerHTML = "";
  if (!state.channels.length) {
    selectedChannelId = null;
    syncChannelConfigVisibility();
    box.innerHTML = '<div class="ch-item">Нет каналов</div>';
    return;
  }
  state.channels.forEach((c) => {
    const run = (c.metrics || {}).state === "running";
    const row = document.createElement("div");
    row.className = `ch-item ${c.id === selectedChannelId ? "active" : ""}`;
    row.innerHTML = `<div class='ch-item-dot ${run ? "" : "off"}'></div> ${c.name}`;
    row.onclick = () => selectChannel(c.id);
    box.appendChild(row);
  });
  if (!state.channels.some((c) => c.id === selectedChannelId)) {
    selectedChannelId = null;
  }
  if (!selectedChannelId) {
    selectedChannelId = state.channels[0].id;
    selectChannel(selectedChannelId);
    return;
  }
  syncChannelConfigVisibility();
}

function toCanvasPoint(point, unit, cv) {
  if (unit === "percent") {
    return {
      x: ((Number(point.x) || 0) * cv.width) / 100,
      y: ((Number(point.y) || 0) * cv.height) / 100,
    };
  }
  return { x: Number(point.x) || 0, y: Number(point.y) || 0 };
}
function toPercentPoint(point, cv) {
  const x = Math.max(0, Math.min(cv.width, Number(point.x) || 0));
  const y = Math.max(0, Math.min(cv.height, Number(point.y) || 0));
  return {
    x: Number(((x / cv.width) * 100).toFixed(3)),
    y: Number(((y / cv.height) * 100).toFixed(3)),
  };
}
function drawROI() {
  const cv = document.getElementById("roiCanvas");
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (roiBgImage && roiBgImage.complete) {
    ctx.drawImage(roiBgImage, 0, 0, cv.width, cv.height);
  }
  ctx.fillStyle = "rgba(124,107,250,0.15)";
  ctx.strokeStyle = "#9b8fff";
  ctx.lineWidth = 2;
  if (roiPoints.length >= 2) {
    ctx.beginPath();
    roiPoints.forEach((p, i) => {
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    });
    if (roiPoints.length >= 3) {
      ctx.closePath();
      ctx.fill();
    }
    ctx.stroke();
  }
  roiPoints.forEach((p) => {
    ctx.fillStyle = "#9b8fff";
    ctx.beginPath();
    ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
    ctx.fill();
  });
}
function refreshROISnapshot() {
  if (!selectedChannelId) return;
  const img = new Image();
  img.onload = () => {
    roiBgImage = img;
    drawROI();
  };
  img.src = api(
    `/api/channels/${selectedChannelId}/snapshot.jpg?t=${Date.now()}`,
  );
}
function setupROI() {
  const cv = document.getElementById("roiCanvas");
  let moved = false;
  let downPoint = null;
  cv.oncontextmenu = (e) => {
    e.preventDefault();
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    const idx = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
    if (idx >= 0) {
      roiPoints.splice(idx, 1);
      drawROI();
      setVal("c_roi_points", JSON.stringify(roiPoints));
    }
  };
  cv.onmousedown = (e) => {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    downPoint = { x, y };
    moved = false;
    roiDrag = roiPoints.findIndex((p) => Math.hypot(p.x - x, p.y - y) < 10);
  };
  cv.onmousemove = (e) => {
    if (roiDrag < 0) return;
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    roiPoints[roiDrag] = { x, y };
    moved = true;
    drawROI();
  };
  cv.onmouseup = (e) => {
    const r = cv.getBoundingClientRect();
    const x = e.clientX - r.left,
      y = e.clientY - r.top;
    if (roiDrag >= 0) {
      roiDrag = -1;
      if (moved) {
        setVal("c_roi_points", JSON.stringify(roiPoints));
        return;
      }
    }
    if (e.button !== 0) return;
    if (downPoint && Math.hypot(downPoint.x - x, downPoint.y - y) > 4) return;
    const nearExisting = roiPoints.findIndex(
      (p) => Math.hypot(p.x - x, p.y - y) < 10,
    );
    if (nearExisting === -1) {
      roiPoints.push({ x, y });
      drawROI();
      setVal("c_roi_points", JSON.stringify(roiPoints));
    }
  };
}


function hotkeyFromEvent(event) {
  const key = String(event.key || "").trim().toUpperCase();
  if (!key || key === "CONTROL" || key === "SHIFT" || key === "ALT") return "";
  const parts = [];
  if (event.ctrlKey) parts.push("CTRL");
  if (event.altKey) parts.push("ALT");
  if (event.shiftKey) parts.push("SHIFT");
  parts.push(key);
  return parts.join("+");
}

function isEditingTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return true;
  return Boolean(target.closest("[contenteditable='true']"));
}

function updateRelayTimerState(relayIndex) {
  const modeEl = document.getElementById(`ctrlR${relayIndex}Mode`);
  const timerEl = document.getElementById(`ctrlR${relayIndex}Timer`);
  if (!modeEl || !timerEl) return;
  const isPulseTimer = modeEl.value === "pulse_timer";
  timerEl.disabled = !isPulseTimer;
  if (!isPulseTimer) {
    timerEl.value = "1";
  }
}

function updateChannelControllerBindingState() {
  const hasController = Boolean(val("c_controller_id"));
  const relayEl = document.getElementById("c_controller_relay");
  relayEl.disabled = !hasController;
  if (!hasController) {
    setVal("c_controller_relay", 0);
  }
}

function renderCustomListOptions(selectedIds = []) {
  const box = document.getElementById("c_list_ids_select");
  if (!box) return;
  const selected = new Set((selectedIds || []).map((id) => Number(id)));
  box.innerHTML = "";
  const selectableLists = state.lists.filter((list) => String(list.type || "").toLowerCase() !== "black");
  selectableLists.forEach((list) => {
    const item = document.createElement("label");
    item.style.display = "flex";
    item.style.alignItems = "center";
    item.style.gap = "6px";
    item.style.marginBottom = "4px";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = String(list.id);
    checkbox.checked = selected.has(Number(list.id));

    const caption = document.createElement("span");
    const typeRaw = String(list.type || "").toLowerCase();
    let listType = "Пользовательский список";
    if (typeRaw === "white") listType = "Белый список";
    else if (typeRaw === "black") listType = "Черный список";
    caption.textContent = `${list.name} (${listType})`;

    item.appendChild(checkbox);
    item.appendChild(caption);
    box.appendChild(item);
  });
}


function getSelectedCustomListIds() {
  const box = document.getElementById("c_list_ids_select");
  if (!box) return [];
  return Array.from(box.querySelectorAll("input[type='checkbox']:checked"))
    .map((el) => Number(el.value))
    .filter((id) => Number.isFinite(id) && id > 0);
}

function updateCustomListsVisibility() {
  const block = document.getElementById("c_custom_lists_block");
  const hint = document.getElementById("c_custom_lists_hint");
  if (!block || !hint) return;
  const isCustom = val("c_list_filter_mode") === "custom";
  block.style.display = isCustom ? "flex" : "none";
  hint.style.display = isCustom ? "flex" : "none";
}

function renderChannelControllerOptions(selectedId = "") {
  const select = document.getElementById("c_controller_id");
  const current = String(selectedId ?? "");
  select.innerHTML = "";
  const noneOption = document.createElement("option");
  noneOption.value = "";
  noneOption.textContent = "Без контроллера";
  select.appendChild(noneOption);
  controllersCache.forEach((controller) => {
    const option = document.createElement("option");
    option.value = String(controller.id);
    option.textContent = controller.name || `Контроллер ${controller.id}`;
    select.appendChild(option);
  });
  select.value = current;
  if (select.value !== current) {
    select.value = "";
  }
  updateChannelControllerBindingState();
}

function rebuildHotkeyMap() {
  hotkeyMap.clear();
  const pending = new Map();
  const duplicates = new Set();
  controllersCache.forEach((controller) => {
    (controller.relays || []).forEach((relay, relayIndex) => {
      const hotkey = String(relay.hotkey || "").trim().toUpperCase();
      if (!hotkey) return;
      const binding = {
        controllerId: controller.id,
        relayIndex,
        controllerName: controller.name || `Контроллер ${controller.id}`,
      };
      if (!pending.has(hotkey)) {
        pending.set(hotkey, [binding]);
      } else {
        pending.get(hotkey).push(binding);
        duplicates.add(hotkey);
      }
    });
  });
  duplicates.forEach((hotkey) => {
    addDebug(`[ERR] duplicate hotkey detected: ${hotkey}. Хоткей отключен до устранения конфликта`, "err");
  });
  pending.forEach((bindings, hotkey) => {
    if (duplicates.has(hotkey)) return;
    hotkeyMap.set(hotkey, bindings[0]);
  });
}

async function triggerHotkey(hotkey) {
  const binding = hotkeyMap.get(hotkey);
  if (!binding) return;
  try {
    const res = await jfetch(api(`/api/controllers/${binding.controllerId}/test`), "POST", {
      relay_index: binding.relayIndex,
      is_on: true,
    });
    addDebug(`[OK] hotkey ${hotkey}: ${binding.controllerName}, реле ${binding.relayIndex + 1}, статус=${res.status}`, "ok");
  } catch (err) {
    addDebug(`[ERR] hotkey ${hotkey}: ${err.message}`, "err");
  }
}

async function selectChannel(id) {
  selectedChannelId = id;
  syncChannelConfigVisibility();
  const requestToken = ++channelConfigRequestToken;
  renderChannelsList();
  const c = await jfetch(api(`/api/channels/${id}/config`));
  if (
    requestToken !== channelConfigRequestToken ||
    Number(selectedChannelId) !== Number(id)
  ) {
    return;
  }
  setVal("c_name", c.name);
  setVal("c_source", c.source);
  renderChannelControllerOptions(c.controller_id ?? "");
  setVal("c_controller_relay", c.controller_relay ?? 0);
  updateChannelControllerBindingState();
  setVal("c_list_filter_mode", c.list_filter_mode || "all");
  currentChannelCustomListIds = (c.list_filter_list_ids || []).map((id) => Number(id)).filter((id) => Number.isFinite(id) && id > 0);
  renderCustomListOptions(currentChannelCustomListIds);
  updateCustomListsVisibility();
  setVal("c_detection_mode", c.detection_mode || "motion");
  setVal("c_motion_threshold", c.motion_threshold ?? 0.01);
  setVal("c_motion_frame_stride", c.motion_frame_stride ?? 1);
  setVal("c_motion_activation", c.motion_activation_frames ?? 3);
  setVal("c_motion_release", c.motion_release_frames ?? 6);
  setVal("c_detector_stride", c.detector_frame_stride ?? 2);
  setChk("c_size_filter", c.size_filter_enabled);
  setVal("c_min_w", c.min_plate_size?.width ?? 80);
  setVal("c_min_h", c.min_plate_size?.height ?? 20);
  setVal("c_max_w", c.max_plate_size?.width ?? 600);
  setVal("c_max_h", c.max_plate_size?.height ?? 240);
  setVal("c_best_shots", c.best_shots ?? 3);
  setVal("c_cooldown", c.cooldown_seconds ?? 5);
  setVal("c_ocr_conf", c.ocr_min_confidence ?? 0.6);
  setChk("c_roi_enabled", c.roi_enabled);
  const cv = document.getElementById("roiCanvas");
  const unit = c.region?.unit || "px";
  roiPoints = (c.region?.points || []).map((p) => toCanvasPoint(p, unit, cv));
  setVal("c_roi_points", JSON.stringify(roiPoints));
  drawROI();
}

async function saveChannel() {
  if (!selectedChannelId) return;
  let points = roiPoints;
  try {
    points = JSON.parse(val("c_roi_points"));
  } catch (_e) {}
  if (
    document.getElementById("c_roi_enabled").checked &&
    points.length > 0 &&
    points.length < 3
  ) {
    alert("Для замкнутой ROI-области нужно минимум 3 точки");
    return;
  }
  const selectedCustomListIds = getSelectedCustomListIds();
  currentChannelCustomListIds = selectedCustomListIds;

  const payload = {
    name: val("c_name"),
    source: val("c_source"),
    controller_id: val("c_controller_id") ? Number(val("c_controller_id")) : null,
    controller_relay: val("c_controller_id") ? Number(val("c_controller_relay")) : 0,
    list_filter_mode: val("c_list_filter_mode"),
    list_filter_list_ids: val("c_list_filter_mode") === "custom" ? selectedCustomListIds : [],
    detection_mode: val("c_detection_mode"),
    motion_threshold: Number(val("c_motion_threshold")),
    motion_frame_stride: Number(val("c_motion_frame_stride")),
    motion_activation_frames: Number(val("c_motion_activation")),
    motion_release_frames: Number(val("c_motion_release")),
    detector_frame_stride: Number(val("c_detector_stride")),
    size_filter_enabled: document.getElementById("c_size_filter").checked,
    min_plate_size: {
      width: Number(val("c_min_w")),
      height: Number(val("c_min_h")),
    },
    max_plate_size: {
      width: Number(val("c_max_w")),
      height: Number(val("c_max_h")),
    },
    best_shots: Number(val("c_best_shots")),
    cooldown_seconds: Number(val("c_cooldown")),
    ocr_min_confidence: Number(val("c_ocr_conf")),
    roi_enabled: document.getElementById("c_roi_enabled").checked,
    region: {
      unit: "percent",
      points: points.map((p) =>
        toPercentPoint(p, document.getElementById("roiCanvas")),
      ),
    },
  };
  await jfetch(
    api(`/api/channels/${selectedChannelId}/config`),
    "PUT",
    payload,
  );
  addDebug(`[OK] channel ${selectedChannelId} saved`, "ok");
  await refreshChannels();
}
async function createChannel() {
  try {
    await jfetch(api("/api/channels"), "POST", {
      name: "Канал",
      source: "0",
      enabled: true,
      roi_enabled: true,
      region: { unit: "percent", points: [] },
    });
    await refreshChannels();
    if (state.channels.length) {
      selectedChannelId = state.channels[state.channels.length - 1].id;
      await selectChannel(selectedChannelId);
    }
    addDebug("[OK] channel created", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось создать канал: ${err.message}`);
  }
}
async function deleteChannel() {
  if (!selectedChannelId) return;
  if (!confirm(`Удалить канал #${selectedChannelId}?`)) return;
  await jfetch(api(`/api/channels/${selectedChannelId}`), "DELETE");
  selectedChannelId = null;
  roiPoints = [];
  await refreshChannels();
  addDebug("[OK] channel deleted", "ok");
}


function setControllerFormDisabled(disabled) {
  [
    "ctrlName",
    "ctrlType",
    "ctrlAddress",
    "ctrlPassword",
    "ctrlR0Mode",
    "ctrlR0Timer",
    "ctrlR0Hotkey",
    "ctrlR1Mode",
    "ctrlR1Timer",
    "ctrlR1Hotkey",
    "testRelay0Btn",
    "testRelay1Btn",
    "saveControllerBtn",
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!disabled;
  });
}

function fillControllerForm(c) {
  if (!c) {
    setVal("ctrlName", "");
    setVal("ctrlType", "DTWONDER2CH");
    setVal("ctrlAddress", "");
    setVal("ctrlPassword", "0");
    setVal("ctrlR0Mode", "pulse");
    setVal("ctrlR0Timer", 1);
    setVal("ctrlR0Hotkey", "");
    setVal("ctrlR1Mode", "pulse");
    setVal("ctrlR1Timer", 1);
    setVal("ctrlR1Hotkey", "");
    setControllerFormDisabled(true);
    return;
  }
  setVal("ctrlName", c.name);
  setVal("ctrlType", c.type);
  setVal("ctrlAddress", c.address);
  setVal("ctrlPassword", c.password);
  setVal("ctrlR0Mode", c.relays?.[0]?.mode || "pulse");
  setVal("ctrlR0Timer", c.relays?.[0]?.timer_seconds || 1);
  setVal("ctrlR0Hotkey", c.relays?.[0]?.hotkey || "");
  setVal("ctrlR1Mode", c.relays?.[1]?.mode || "pulse");
  setVal("ctrlR1Timer", c.relays?.[1]?.timer_seconds || 1);
  setVal("ctrlR1Hotkey", c.relays?.[1]?.hotkey || "");
  setControllerFormDisabled(false);
  updateRelayTimerState(0);
  updateRelayTimerState(1);
}
function renderControllerItems() {
  const box = document.getElementById("controllerItems");
  box.innerHTML = "";
  if (!controllersCache.length) {
    box.innerHTML = '<div class="ch-item">Нет контроллеров</div>';
    setControllerFormDisabled(true);
    syncControllerConfigVisibility();
    return;
  }
  controllersCache.forEach((c) => {
    const row = document.createElement("div");
    row.className = `ch-item ${c.id === selectedControllerId ? "active" : ""}`;
    row.textContent = c.name;
    row.onclick = () => selectController(c.id);
    box.appendChild(row);
  });
}
function selectController(id) {
  selectedControllerId = id;
  syncControllerConfigVisibility();
  const item = controllersCache.find((c) => c.id === id);
  fillControllerForm(item || null);
  renderControllerItems();
}
async function loadControllers() {
  controllersCache = await jfetch(api("/api/controllers"));
  if (controllersCache.length) {
    if (
      !selectedControllerId ||
      !controllersCache.some((c) => c.id === selectedControllerId)
    ) {
      selectedControllerId = controllersCache[0].id;
    }
    selectController(selectedControllerId);
  } else {
    selectedControllerId = null;
    fillControllerForm(null);
    renderControllerItems();
  }
  syncControllerConfigVisibility();
  rebuildHotkeyMap();
  renderChannelControllerOptions(val("c_controller_id"));
  renderControllerItems();
}
function controllerPayload() {
  return {
    name: val("ctrlName"),
    type: val("ctrlType") || "DTWONDER2CH",
    address: val("ctrlAddress"),
    password: val("ctrlPassword") || "0",
    relays: [
      {
        mode: val("ctrlR0Mode") || "pulse",
        timer_seconds: val("ctrlR0Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR0Timer") || 1)) : 1,
        hotkey: (val("ctrlR0Hotkey") || "").trim().toUpperCase(),
      },
      {
        mode: val("ctrlR1Mode") || "pulse",
        timer_seconds: val("ctrlR1Mode") === "pulse_timer" ? Math.max(1, Number(val("ctrlR1Timer") || 1)) : 1,
        hotkey: (val("ctrlR1Hotkey") || "").trim().toUpperCase(),
      },
    ],
  };
}
async function createController() {
  const body = controllerPayload();
  if (!body.name) {
    body.name = "Контроллер";
  }
  try {
    await jfetch(api("/api/controllers"), "POST", body);
    await loadControllers();
    if (controllersCache.length) {
      selectedControllerId = controllersCache[controllersCache.length - 1].id;
      selectController(selectedControllerId);
    }
    addDebug("[OK] controller created", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось создать контроллер: ${err.message}`);
  }
}
async function saveController() {
  if (!selectedControllerId) return;
  try {
    await jfetch(
      api(`/api/controllers/${selectedControllerId}`),
      "PUT",
      controllerPayload(),
    );
    await loadControllers();
    addDebug("[OK] controller updated", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(`Не удалось сохранить контроллер: ${err.message}`);
  }
}
async function deleteController() {
  if (!selectedControllerId) return;
  if (!confirm("Удалить выбранный контроллер?")) return;
  try {
    await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE");
    await loadControllers();
    addDebug("[OK] controller deleted", "ok");
  } catch (err) {
    addDebug(`[ERR] ${err.message}`, "err");
    alert(err.message);
  }
}
async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", {
    relay_index: relay,
    is_on: true,
  });
  addDebug(`[OK] relay ${relay + 1} test sent`, "ok");
}

function mapLogClass(level) {
  const v = String(level || "INFO").toUpperCase();
  if (v === "ERROR" || v === "CRITICAL") return "err";
  if (v === "WARNING") return "warn";
  if (v === "DEBUG") return "ok";
  return "info";
}

function prependDebugLine(text, type = "info", timestamp = null, meta = "") {
  const log = document.getElementById("debugLog");
  if (!log) return;
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  const ts = timestamp ? new Date(timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
  line.innerHTML = `<span class='log-ts'>${ts}</span>${meta ? ` <span class='log-meta'>${meta}</span>` : ""} ${text}`;
  log.prepend(line);
  while (log.children.length > 300) log.removeChild(log.lastElementChild);
}

function addDebug(msg, type = "info") {
  prependDebugLine(msg, type, null, "[UI]");
}

function applyDebugPanelVisibility() {
  const panel = document.getElementById("obsDebugPanel");
  if (!panel) return;
  const enabled = Boolean((debugSettingsCache || {}).log_panel_enabled);
  panel.style.display = enabled ? "flex" : "none";
}

function scheduleDebugLogReconnect(delayMs = 2000) {
  if (debugLogReconnectTimer) return;
  debugLogReconnectTimer = setTimeout(() => {
    debugLogReconnectTimer = null;
    setupDebugLogStream();
  }, delayMs);
}

async function loadDebugLogHistory() {
  try {
    const payload = await jfetch(api("/api/debug/logs?limit=150"));
    const items = Array.isArray(payload.items) ? payload.items : [];
    items.reverse().forEach((item) => {
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    });
  } catch (err) {
    prependDebugLine(`[WARN] не удалось загрузить историю логов: ${err.message}`, "warn");
  }
}

function setupDebugLogStream() {
  if (debugLogSource) {
    try { debugLogSource.close(); } catch (_e) {}
  }
  debugLogSource = new EventSource(api(`/api/debug/logs/stream?last_id=${lastDebugLogId}`));
  debugLogSource.onmessage = (evt) => {
    try {
      const item = JSON.parse(evt.data);
      lastDebugLogId = Math.max(lastDebugLogId, Number(item.id || 0));
      const prefix = `[${item.level}] ${item.service}/${item.logger}${item.channel_id ? ` #${item.channel_id}` : ""}`;
      prependDebugLine(item.message, mapLogClass(item.level), item.timestamp, prefix);
    } catch (_e) {}
  };
  debugLogSource.onerror = () => {
    try { debugLogSource.close(); } catch (_e) {}
    scheduleDebugLogReconnect();
  };
}
function scheduleStreamReconnect(delayMs = 3000) {
  if (streamReconnectTimer) return;
  streamReconnectTimer = setTimeout(() => {
    streamReconnectTimer = null;
    setupStream();
  }, delayMs);
}

async function setupStream() {
  if (streamReconnectTimer) {
    clearTimeout(streamReconnectTimer);
    streamReconnectTimer = null;
  }
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
  }
  eventSource = new EventSource(api("/api/events/stream"));
  eventSource.onmessage = (m) => {
    try {
      pushEvent(JSON.parse(m.data));
    } catch (_e) {}
  };
  eventSource.onerror = () => {
    addDebug("[WARN] stream reconnect", "warn");
    try {
      eventSource.close();
    } catch (_e) {}
    scheduleStreamReconnect();
  };
}
function fillChannelFilter() {
  const sel = document.getElementById("fltChannel");
  const cur = sel.value;
  sel.innerHTML = '<option value="">Все каналы</option>';
  state.channels.forEach((c) => {
    const o = document.createElement("option");
    o.value = String(c.channel || c.id);
    o.textContent = `CAM-${String(c.id).padStart(2, "0")}`;
    sel.appendChild(o);
  });
  sel.value = cur;
}
function closeEventModal() {
  document.getElementById("eventModal").classList.remove("active");
}
function setModalImage(id, url) {
  const img = document.getElementById(id);
  if (!url) {
    img.removeAttribute("src");
    img.alt = "Нет изображения";
    return;
  }
  img.src = url;
}
async function openEventDetails(ev) {
  const id = Number(ev.id || 0);
  let payload = ev;
  if (id > 0) {
    try {
      payload = await jfetch(api(`/api/events/item/${id}`));
    } catch (err) {
      addDebug(
        `[WARN] event details fallback for id=${id}: ${err.message}`,
        "warn",
      );
      payload = ev;
    }
  }
  const ts = payload.timestamp
    ? new Date(payload.timestamp).toLocaleString()
    : "—";
  const rows = [
    ["Дата/время", ts],
    ["Канал", payload.channel || `CAM-${payload.channel_id || ""}`],
    ["Страна", payload.country || "—"],
    ["Гос. номер", payload.plate || "—"],
    ["Уверенность", Number(payload.confidence || 0).toFixed(2)],
    ["Направление", formatDirection(payload.direction).plain],
    ["Источник", payload.source || "—"],
  ];
  const meta = document.getElementById("eventMeta");
  meta.innerHTML = rows
    .map(
      (r) =>
        `<div class="event-meta-row"><span>${r[0]}</span><b>${r[1]}</b></div>`,
    )
    .join("");
  if (id > 0) {
    setModalImage("eventFrameImg", api(`/api/events/item/${id}/media/frame`));
    setModalImage("eventPlateImg", api(`/api/events/item/${id}/media/plate`));
  } else {
    setModalImage("eventFrameImg", null);
    setModalImage("eventPlateImg", null);
  }
  document.getElementById("eventModal").classList.add("active");
}

const toggleDebugPanelBtn = document.getElementById("toggleDebugPanelBtn");
if (toggleDebugPanelBtn) {
  toggleDebugPanelBtn.onclick = () => {
    const panel = document.getElementById("obsDebugPanel");
    const log = document.getElementById("debugLog");
    if (!panel || !log) return;
    const collapsed = panel.dataset.collapsed === "1";
    panel.dataset.collapsed = collapsed ? "0" : "1";
    log.style.display = collapsed ? "block" : "none";
    toggleDebugPanelBtn.textContent = collapsed ? "Свернуть" : "Развернуть";
  };
};

document
  .querySelectorAll(".ttab")
  .forEach((el) => (el.onclick = () => switchTab(el.dataset.tab)));
document
  .querySelectorAll(".snav-item")
  .forEach((el) => (el.onclick = () => switchSettings(el.dataset.sp)));
document
  .querySelectorAll(".ch-tab")
  .forEach(
    (el) => (el.onclick = () => switchChannelSettingsTab(el.dataset.chTab)),
  );
document.getElementById("gridSelect").onchange = renderVideoGrid;
document.getElementById("btnFind").onclick = renderJournal;
document.getElementById("btnReset").onclick = () => {
  document.getElementById("fltPlate").value = "";
  document.getElementById("fltChannel").value = "";
  renderJournal();
};
document.getElementById("btnExport").onclick = () =>
  window.open(api("/api/data/export/events.csv"), "_blank");
document.getElementById("addListBtn").onclick = async () => {
  const name = prompt("Название списка");
  if (!name) return;
  const type = prompt("Тип: white/black", "white") || "white";
  await jfetch(api("/api/lists"), "POST", { name, type });
  await loadLists();
};
document.getElementById("addEntryBtn").onclick = async () => {
  if (!state.selectedListId) return;
  const plate = prompt("Номер");
  if (!plate) return;
  const comment = prompt("Комментарий", "") || "";
  await jfetch(api(`/api/lists/${state.selectedListId}/entries`), "POST", {
    plate,
    comment,
  });
  await loadEntries(state.selectedListId);
};
document.getElementById("exportListBtn").onclick = () =>
  window.open(api("/api/data/export/events.csv"), "_blank");
document.getElementById("eventModalClose").onclick = closeEventModal;
document.getElementById("eventModal").onclick = (e) => {
  if (e.target.id === "eventModal") closeEventModal();
};
document.getElementById("saveGeneralBtn").onclick = saveGeneral;
document.getElementById("saveChannelBtn").onclick = saveChannel;
document.getElementById("deleteChannelBtn").onclick = deleteChannel;
document.getElementById("createChannelBtn").onclick = createChannel;
document.getElementById("createControllerBtn").onclick = createController;
document.getElementById("saveControllerBtn").onclick = saveController;
document.getElementById("deleteControllerBtn").onclick = deleteController;
document.getElementById("testRelay0Btn").onclick = () => testController(0);
document.getElementById("testRelay1Btn").onclick = () => testController(1);
document.getElementById("ctrlR0Mode").onchange = () => updateRelayTimerState(0);
document.getElementById("ctrlR1Mode").onchange = () => updateRelayTimerState(1);
document.getElementById("c_controller_id").onchange = updateChannelControllerBindingState;
document.getElementById("c_list_filter_mode").onchange = updateCustomListsVisibility;
document.getElementById("saveDebugBtn").onclick = saveGeneral;
document.getElementById("g_theme").onchange = () => applyTheme(val("g_theme"));
document.getElementById("themeToggleBtn").onclick = () => {
  const nextTheme = val("g_theme") === "light" ? "dark" : "light";
  setVal("g_theme", nextTheme);
  applyTheme(nextTheme);
};
document.getElementById("roiRefreshBtn").onclick = refreshROISnapshot;
document.getElementById("roiClearBtn").onclick = () => {
  roiPoints = [];
  setVal("c_roi_points", "[]");
  drawROI();
};
document.getElementById("roiApplyBtn").onclick = () =>
  setVal("c_roi_points", JSON.stringify(roiPoints));


document.addEventListener("keydown", (event) => {
  if (event.repeat || isEditingTarget(event.target)) return;
  const hotkey = hotkeyFromEvent(event);
  if (!hotkey || !hotkeyMap.has(hotkey)) return;
  event.preventDefault();
  triggerHotkey(hotkey);
});

refreshSystemResources();
setInterval(refreshSystemResources, 2000);
window.addEventListener("beforeunload", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  if (debugLogSource) {
    try {
      debugLogSource.close();
    } catch (_e) {}
    debugLogSource = null;
  }
});
window.addEventListener("pagehide", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
  if (debugLogSource) {
    try {
      debugLogSource.close();
    } catch (_e) {}
    debugLogSource = null;
  }
});
window.addEventListener("resize", renderEventFeed);
(async function init() {
  document.getElementById("apiBase").value = window.location.origin;
  try {
    applyTheme(localStorage.getItem("anpr_theme") || "dark");
  } catch (_e) {
    applyTheme("dark");
  }
  syncChannelConfigVisibility();
  syncControllerConfigVisibility();
  setupVideoGridLayoutGuards();
  setupROI();
  switchChannelSettingsTab("channel");
  updateTopbarTitle();
  await refreshChannels();
  await hydrateChannelLastPlates();
  await loadJournal();
  await loadLists();
  await loadGlobalSettings();
  await loadDebugLogHistory();
  setupDebugLogStream();
  await loadControllers();
  setupStream();
  addDebug("[INFO] UI initialized");
  setInterval(refreshChannels, 8000);
})();
