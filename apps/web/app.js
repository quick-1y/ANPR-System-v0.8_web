const state = {
  channels: [],
  lists: [],
  selectedListId: null,
  allEvents: [],
};
let eventSource = null;
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
}
function switchSettings(name) {
  document
    .querySelectorAll(".snav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.sp === name));
  document
    .querySelectorAll(".settings-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`sp-${name}`).classList.add("active");
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
  return `<div class='cam-no-signal'><svg width='32' height='32' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><path d='M23 7l-7 5 7 5V7z'/><rect x='1' y='5' width='15' height='14' rx='2'/></svg><p>${statusText}</p></div>`;
}

function ensurePreviewStream(img, channelId) {
  if (!img) return;
  const url = api(`/api/channels/${channelId}/preview.mjpg`);
  if (img.dataset.url !== url) {
    img.dataset.url = url;
    img.src = url;
  }
}

function createVideoCell(ch, idx) {
  const previewReady = Boolean((ch.metrics || {}).preview_ready);
  const statusText = statusTextForChannel(ch);
  const cell = document.createElement("div");
  cell.className = `video-cell ${idx === 0 ? "active" : ""}`;
  cell.dataset.channelId = String(ch.id);
  const noSignalHtml = previewReady ? "" : buildNoSignalHtml(statusText);
  cell.innerHTML = `<div class='video-cell-bg'></div><img id='v-${ch.id}' alt='preview CAM-${ch.id}' />${noSignalHtml}<div class='cam-label'>CAM-${String(ch.id).padStart(2, "0")} · ${ch.name}</div><div class='cam-status ${previewReady ? "live" : "off"}'></div><div class='cam-plate' id='plate-${ch.id}'></div>`;
  ensurePreviewStream(cell.querySelector("img"), ch.id);
  return cell;
}

function updateVideoCell(cell, ch, idx) {
  const previewReady = Boolean((ch.metrics || {}).preview_ready);
  cell.classList.toggle("active", idx === 0);
  const label = cell.querySelector(".cam-label");
  if (label)
    label.textContent = `CAM-${String(ch.id).padStart(2, "0")} · ${ch.name}`;
  const statusDot = cell.querySelector(".cam-status");
  if (statusDot) {
    statusDot.classList.toggle("live", previewReady);
    statusDot.classList.toggle("off", !previewReady);
  }
  const existingNoSignal = cell.querySelector(".cam-no-signal");
  if (previewReady) {
    if (existingNoSignal) existingNoSignal.remove();
  } else {
    const statusText = statusTextForChannel(ch);
    if (existingNoSignal) {
      const statusTextNode = existingNoSignal.querySelector("p");
      if (statusTextNode) statusTextNode.textContent = statusText;
    } else {
      const img = cell.querySelector("img");
      if (img)
        img.insertAdjacentHTML("afterend", buildNoSignalHtml(statusText));
    }
  }
  ensurePreviewStream(cell.querySelector("img"), ch.id);
}

function renderVideoGrid() {
  const grid = document.getElementById("videoGrid");
  const [rows, cols] = gridConfig(document.getElementById("gridSelect").value);
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
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

function renderEventFeed() {
  const feed = document.getElementById("eventFeed");
  if (!feed) return;
  feed.innerHTML = "";
  const events = state.allEvents;
  for (const [i, item] of events.entries()) {
    const conf = Number(item.confidence || 0);
    const div = document.createElement("div");
    div.className = `ev-item ${i === 0 ? "hot" : ""}`;
    div.innerHTML = `${flagHtml(item.country)}<div class='ev-body'><div class='ev-plate'>${item.plate || "—"}</div><div class='ev-meta'>${item.channel || `CAM-${item.channel_id || ""}`} · <span>${new Date(item.timestamp || Date.now()).toLocaleTimeString()}</span></div></div><div class='ev-conf ${conf < 0.85 ? "warn" : ""}'>${conf.toFixed(2)}</div>`;
    div.onclick = () => highlightPlate(item);
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
  state.allEvents.unshift(ev);
  if (state.allEvents.length > 500) state.allEvents.pop();
  renderEventFeed();
  renderJournal();
  addDebug(
    `[INFO] event: ${ev.plate || "-"} conf=${Number(ev.confidence || 0).toFixed(2)}`,
    "ok",
  );
}
function highlightPlate(ev) {
  const ch = state.channels.find(
    (c) =>
      String(c.name) === String(ev.channel) ||
      Number(c.id) === Number(ev.channel_id),
  );
  if (!ch) return;
  const plate = document.getElementById(`plate-${ch.id}`);
  if (!plate) return;
  plate.textContent = ev.plate || "";
  plate.style.display = "block";
  setTimeout(() => (plate.style.display = "none"), 3000);
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
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${new Date(ev.timestamp).toLocaleTimeString()}</td><td>${ev.channel || `CAM-${ev.channel_id || ""}`}</td><td>${flagHtml(ev.country)} ${ev.country || ""}</td><td><span class='badge ${(ev.direction || "in") === "in" ? "badge-in" : "badge-out"}'>${(ev.direction || "in") === "in" ? "→ Въезд" : "← Выезд"}</span></td><td class='plate-cell'>${ev.plate || ""}</td><td class='conf-cell' style='color:${conf < 0.85 ? "var(--warning)" : "var(--success)"}'>${conf.toFixed(2)}</td><td>${ev.source || ""}</td>`;
    tr.onclick = () => openEventDetails(ev);
    body.appendChild(tr);
  });
}

async function loadLists() {
  state.lists = await jfetch(api("/api/lists"));
  renderLists();
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

async function loadGlobalSettings() {
  const g = await jfetch(api("/api/settings"));
  setVal("g_grid", g.grid);
  setVal("g_theme", g.theme);
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
}

async function saveGeneral() {
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
  await jfetch(api("/api/settings"), "PUT", payload);
  addDebug("[OK] global settings saved", "ok");
}

function renderChannelsList() {
  const box = document.getElementById("channelsList");
  box.innerHTML = "";
  if (!state.channels.length) {
    box.innerHTML = '<div class="ch-item">Нет каналов</div>';
    return;
  }
  state.channels.forEach((c) => {
    const run = (c.metrics || {}).state === "running";
    const row = document.createElement("div");
    row.className = `ch-item ${c.id === selectedChannelId ? "active" : ""}`;
    row.innerHTML = `<div class='ch-item-dot ${run ? "" : "off"}'></div> CAM-${String(c.id).padStart(2, "0")} · ${c.name}`;
    row.onclick = () => selectChannel(c.id);
    box.appendChild(row);
  });
  if (!selectedChannelId) {
    selectedChannelId = state.channels[0].id;
    selectChannel(selectedChannelId);
  }
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

async function selectChannel(id) {
  selectedChannelId = id;
  const requestToken = ++channelConfigRequestToken;
  renderChannelsList();
  const c = await jfetch(api(`/api/channels/${id}/config`));
  if (
    requestToken !== channelConfigRequestToken ||
    Number(selectedChannelId) !== Number(id)
  ) {
    return;
  }
  setVal("c_id", c.id);
  setVal("c_name", c.name);
  setVal("c_source", c.source);
  setChk("c_enabled", c.enabled);
  setVal("c_controller_id", c.controller_id ?? "");
  setVal("c_controller_relay", c.controller_relay ?? 0);
  setVal("c_controller_action", c.controller_action || "on");
  setVal("c_list_filter_mode", c.list_filter_mode || "all");
  setVal("c_list_ids", (c.list_filter_list_ids || []).join(","));
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
  const payload = {
    name: val("c_name"),
    source: val("c_source"),
    enabled: document.getElementById("c_enabled").checked,
    controller_id: val("c_controller_id")
      ? Number(val("c_controller_id"))
      : null,
    controller_relay: Number(val("c_controller_relay")),
    controller_action: val("c_controller_action"),
    list_filter_mode: val("c_list_filter_mode"),
    list_filter_list_ids: parseIds(val("c_list_ids")),
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
  const name = prompt("Название канала", "Канал");
  if (!name) return;
  const source = prompt("Источник RTSP/source", "0") || "0";
  await jfetch(api("/api/channels"), "POST", {
    name,
    source,
    enabled: true,
    roi_enabled: true,
    region: { unit: "percent", points: [] },
  });
  await refreshChannels();
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
}
function renderControllerItems() {
  const box = document.getElementById("controllerItems");
  box.innerHTML = "";
  if (!controllersCache.length) {
    box.innerHTML = '<div class="ch-item">Нет контроллеров</div>';
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
  const item = controllersCache.find((c) => c.id === id);
  fillControllerForm(item || null);
  const sel = document.getElementById("ctrlSelect");
  sel.value = id ? String(id) : "";
  renderControllerItems();
}
async function loadControllers() {
  controllersCache = await jfetch(api("/api/controllers"));
  const sel = document.getElementById("ctrlSelect");
  sel.innerHTML = "";
  controllersCache.forEach((c) => {
    const o = document.createElement("option");
    o.value = String(c.id);
    o.textContent = `${c.name}`;
    sel.appendChild(o);
  });
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
  }
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
        timer_seconds: Number(val("ctrlR0Timer") || 1),
        hotkey: val("ctrlR0Hotkey") || "",
      },
      {
        mode: val("ctrlR1Mode") || "pulse",
        timer_seconds: Number(val("ctrlR1Timer") || 1),
        hotkey: val("ctrlR1Hotkey") || "",
      },
    ],
  };
}
async function createController() {
  const body = controllerPayload();
  if (!body.name) {
    body.name = "Контроллер";
  }
  await jfetch(api("/api/controllers"), "POST", body);
  await loadControllers();
  if (controllersCache.length) {
    selectedControllerId = controllersCache[controllersCache.length - 1].id;
    selectController(selectedControllerId);
  }
  addDebug("[OK] controller created", "ok");
}
async function saveController() {
  if (!selectedControllerId) return;
  await jfetch(
    api(`/api/controllers/${selectedControllerId}`),
    "PUT",
    controllerPayload(),
  );
  await loadControllers();
  addDebug("[OK] controller updated", "ok");
}
async function deleteController() {
  if (!selectedControllerId) return;
  if (!confirm("Удалить выбранный контроллер?")) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}`), "DELETE");
  await loadControllers();
  addDebug("[OK] controller deleted", "ok");
}
async function testController(relay) {
  if (!selectedControllerId) return;
  await jfetch(api(`/api/controllers/${selectedControllerId}/test`), "POST", {
    relay_index: relay,
    is_on: true,
  });
  addDebug(`[OK] relay ${relay} test sent`, "ok");
}

function addDebug(msg, type = "info") {
  const log = document.getElementById("debugLog");
  const line = document.createElement("div");
  line.className = `log-line ${type}`;
  line.innerHTML = `<span class='log-ts'>${new Date().toLocaleTimeString()}</span> ${msg}`;
  log.prepend(line);
  const maxLines = 300;
  while (log.children.length > maxLines) {
    log.removeChild(log.lastElementChild);
  }
}
async function setupStream() {
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
  eventSource.onerror = () => addDebug("[WARN] stream reconnect", "warn");
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
    ["Направление", payload.direction || "—"],
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
document.getElementById("saveDebugBtn").onclick = saveGeneral;
document.getElementById("ctrlSelect").onchange = (e) =>
  selectController(Number(e.target.value));
document.getElementById("roiRefreshBtn").onclick = refreshROISnapshot;
document.getElementById("roiRefreshBtnBottom").onclick = refreshROISnapshot;
document.getElementById("roiClearBtn").onclick = () => {
  roiPoints = [];
  setVal("c_roi_points", "[]");
  drawROI();
};
document.getElementById("roiApplyBtn").onclick = () =>
  setVal("c_roi_points", JSON.stringify(roiPoints));

refreshSystemResources();
setInterval(refreshSystemResources, 2000);
window.addEventListener("beforeunload", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
});
window.addEventListener("pagehide", () => {
  if (eventSource) {
    try {
      eventSource.close();
    } catch (_e) {}
    eventSource = null;
  }
});
window.addEventListener("resize", renderEventFeed);
(async function init() {
  document.getElementById("apiBase").value = window.location.origin;
  setupROI();
  switchChannelSettingsTab("channel");
  await refreshChannels();
  await loadJournal();
  await loadLists();
  await loadGlobalSettings();
  await loadControllers();
  setupStream();
  addDebug("[INFO] UI initialized");
  setInterval(refreshChannels, 8000);
})();
