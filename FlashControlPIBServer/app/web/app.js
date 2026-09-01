"use strict";

const API = "/api/v1";
const titles = {
  dashboard: ["ЦЕНТР МОНИТОРИНГА", "Обзор"],
  devices: ["ИНВЕНТАРИЗАЦИЯ", "USB-устройства"],
  computers: ["ИНФРАСТРУКТУРА", "Компьютеры"],
  agents: ["ИНФРАСТРУКТУРА", "Состояние агентов"],
  events: ["ЖУРНАЛ АУДИТА", "События"],
  alerts: ["IDENTITY ENGINE", "Коллизии и клоны"],
  audit: ["БЕЗОПАСНОСТЬ", "Журнал действий"],
};
const state = { page: "dashboard", offset: 0, limit: 25, filters: {} };
let currentUser = null;
const content = document.getElementById("content");
const drawer = document.getElementById("drawer");
const backdrop = document.getElementById("drawer-backdrop");

function esc(value) {
  return String(value ?? "—").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? esc(value) : date.toLocaleString("ru-RU", { hour12: false });
}

function shortHash(value) {
  return value ? `<span class="mono hash" title="${esc(value)}">${esc(value.slice(0, 12))}…</span>` : "—";
}

function badge(value) {
  const kind = value === "SAME" ? "same" :
    ["SERIAL_COLLISION", "CLONE_SUSPECTED"].includes(value) ? "alert" :
    value === "LIKELY_SAME" ? "info" : "warning";
  return `<span class="badge ${kind}">${esc(value || "UNKNOWN")}</span>`;
}

async function api(path, params = {}) {
  const url = new URL(API + path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, value);
  });
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("Требуется вход");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

function loading() {
  content.innerHTML = '<div class="loading"><div><div class="spinner"></div><p>Загрузка данных…</p></div></div>';
}

function showError(error) {
  content.innerHTML = `<div class="panel empty"><strong>Не удалось загрузить данные</strong><p>${esc(error.message)}</p></div>`;
  const toast = document.getElementById("toast");
  toast.textContent = error.message;
  toast.hidden = false;
  setTimeout(() => { toast.hidden = true; }, 5000);
}

function panelTable(headers, rows, emptyText = "Данных пока нет") {
  return `<div class="panel"><div class="table-wrap"><table><thead><tr>${headers.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="empty">${esc(emptyText)}</td></tr>`}</tbody></table></div></div>`;
}

function pagination(data) {
  const start = data.total ? data.offset + 1 : 0;
  const end = Math.min(data.offset + data.items.length, data.total);
  return `<div class="pagination"><span>${start}–${end} из ${data.total}</span><div><button class="button ghost" data-page-offset="${Math.max(0, data.offset - data.limit)}" ${data.offset === 0 ? "disabled" : ""}>Назад</button> <button class="button ghost" data-page-offset="${data.offset + data.limit}" ${end >= data.total ? "disabled" : ""}>Далее</button></div></div>`;
}

function bindPagination() {
  document.querySelectorAll("[data-page-offset]").forEach(button => button.addEventListener("click", () => {
    state.offset = Number(button.dataset.pageOffset);
    render();
  }));
}

async function renderDashboard() {
  const [stats, alerts, events] = await Promise.all([
    api("/dashboard"), api("/identity-alerts", { limit: 5 }), api("/observations", { limit: 6 })
  ]);
  const metrics = [
    ["Компьютеры", stats.computers], ["Физические устройства", stats.physical_devices],
    ["Наблюдения", stats.observations], ["Media states", stats.media_states],
    ["Агенты онлайн", `${stats.agents_online}/${stats.agents}`],
    ["Очередь не пуста", stats.agents_with_backlog, stats.agents_with_backlog ? "alert" : ""],
    ["Требуют внимания", stats.identity_alerts, "alert"],
  ].map(item => `<article class="metric ${item[2] || ""}"><p>${esc(item[0])}</p><strong>${item[1]}</strong></article>`).join("");
  const results = Object.entries(stats.identity_results || {});
  const max = Math.max(1, ...results.map(([, count]) => count));
  const bars = results.length ? results.map(([name, count]) => `<div class="bar-row"><span>${badge(name)}</span><div class="bar-track"><div class="bar-fill ${["SERIAL_COLLISION", "CLONE_SUSPECTED"].includes(name) ? "warning" : ""}" style="width:${Math.max(3, count / max * 100)}%"></div></div><strong>${count}</strong></div>`).join("") : '<div class="empty">Решений пока нет</div>';
  const eventRows = events.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${formatDate(item.observed_at_utc)}</td><td><span class="primary">${esc(item.hostname)}</span><span class="secondary mono">${esc(item.event_id)}</span></td><td>${badge(item.identity_decision?.result)}</td></tr>`).join("");
  const alertRows = alerts.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${badge(item.result)}</td><td>${esc(item.hostname)}</td><td>${formatDate(item.observed_at_utc)}</td></tr>`).join("");
  content.innerHTML = `<div class="metric-grid">${metrics}</div><div class="split-grid"><div class="panel"><div class="panel-head"><div><h2>Последние события</h2><p>Свежие наблюдения агентов</p></div></div><div class="table-wrap"><table><thead><tr><th>Время</th><th>Источник</th><th>Решение</th></tr></thead><tbody>${eventRows || '<tr><td colspan="3" class="empty">Событий пока нет</td></tr>'}</tbody></table></div></div><div class="panel"><div class="panel-head"><div><h2>Identity Engine</h2><p>Распределение решений</p></div></div><div class="bar-list">${bars}</div></div></div><div class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Активные предупреждения</h2><p>Коллизии serial и подозрения на клон</p></div></div><div class="table-wrap"><table><thead><tr><th>Тип</th><th>Компьютер</th><th>Время</th></tr></thead><tbody>${alertRows || '<tr><td colspan="3" class="empty">Предупреждений нет</td></tr>'}</tbody></table></div></div>`;
  bindRows();
}

async function renderDevices() {
  const data = await api("/devices", { limit: state.limit, offset: state.offset, status: state.filters.status, hardware_hash: state.filters.hash });
  const rows = data.items.map(item => `<tr class="clickable" data-device="${esc(item.id)}"><td><span class="primary">${esc([item.vendor, item.product].filter(Boolean).join(" ") || "Неизвестное устройство")}</span><span class="secondary mono">${esc(item.id)}</span></td><td>${item.vid || item.pid ? `${esc(item.vid)}:${esc(item.pid)}` : "—"}</td><td class="mono">${esc(item.storage_serial)}</td><td>${shortHash(item.hardware_stable_sha256)}</td><td><span class="badge ${item.identity_confidence === "high" ? "same" : "warning"}">${esc(item.identity_confidence)}</span></td><td>${formatDate(item.last_seen_at)}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="device-hash" placeholder="Полный hardware hash" value="${esc(state.filters.hash || "")}"><select class="field" id="device-status"><option value="">Все статусы</option><option value="provisional" ${state.filters.status === "provisional" ? "selected" : ""}>provisional</option></select><button class="button" id="device-filter">Применить</button></div>${panelTable(["Устройство", "VID:PID", "Storage serial", "Hardware hash", "Confidence", "Последнее наблюдение"], rows)}${pagination(data)}`;
  document.getElementById("device-filter").onclick = () => { state.filters = { hash: document.getElementById("device-hash").value.trim(), status: document.getElementById("device-status").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderComputers() {
  const data = await api("/computers", { limit: state.limit, offset: state.offset, hostname: state.filters.hostname });
  const rows = data.items.map(item => `<tr class="clickable" data-computer="${esc(item.id)}"><td><span class="primary">${esc(item.hostname)}</span><span class="secondary mono">${esc(item.id)}</span></td><td>${esc(item.domain)}</td><td>${formatDate(item.first_seen_at)}</td><td>${formatDate(item.last_seen_at)}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="computer-search" placeholder="Имя компьютера" value="${esc(state.filters.hostname || "")}"><button class="button" id="computer-filter">Найти</button></div>${panelTable(["Компьютер", "Домен", "Первое наблюдение", "Последнее наблюдение"], rows)}${pagination(data)}`;
  document.getElementById("computer-filter").onclick = () => { state.filters = { hostname: document.getElementById("computer-search").value.trim() }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderAgents() {
  const data = await api("/agents", { limit: state.limit, offset: state.offset, hostname: state.filters.hostname, status: state.filters.status });
  const rows = data.items.map(item => `<tr class="clickable" data-agent="${esc(item.id)}"><td><span class="primary">${esc(item.hostname)}</span><span class="secondary mono">${esc(item.id)}</span></td><td><span class="badge ${item.status === "online" ? "same" : "alert"}">${esc(item.status.toUpperCase())}</span></td><td>${esc(item.agent_version)}</td><td>${item.queue_size ? `<span class="badge warning">${item.queue_size}</span>` : "0"}</td><td>${esc(item.selected_route)}</td><td>${formatDate(item.last_seen_at_utc)}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="agent-search" placeholder="Имя компьютера" value="${esc(state.filters.hostname || "")}"><select class="field" id="agent-status"><option value="">Все статусы</option><option value="online" ${state.filters.status === "online" ? "selected" : ""}>online</option><option value="offline" ${state.filters.status === "offline" ? "selected" : ""}>offline</option></select><button class="button" id="agent-filter">Применить</button></div>${panelTable(["Агент", "Статус", "Версия", "Очередь", "Маршрут", "Последний heartbeat"], rows, "Агенты ещё не зарегистрированы")}${pagination(data)}`;
  document.getElementById("agent-filter").onclick = () => { state.filters = { hostname: document.getElementById("agent-search").value.trim(), status: document.getElementById("agent-status").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderEvents() {
  const data = await api("/observations", { limit: state.limit, offset: state.offset, event_type: state.filters.type, decision: state.filters.decision });
  const rows = data.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${formatDate(item.observed_at_utc)}</td><td><span class="primary">${esc(item.hostname)}</span><span class="secondary">${esc(item.user_sid)}</span></td><td>${esc(item.event_type)}</td><td>${badge(item.identity_decision?.result)}</td><td>${shortHash(item.hardware_stable_sha256)}</td><td class="mono">${esc(item.event_id)}</td></tr>`).join("");
  const decisions = ["SAME", "LIKELY_SAME", "UNKNOWN", "SERIAL_COLLISION", "CLONE_SUSPECTED", "DIFFERENT"];
  content.innerHTML = `<div class="toolbar"><select class="field" id="event-decision"><option value="">Все решения</option>${decisions.map(x => `<option ${state.filters.decision === x ? "selected" : ""}>${x}</option>`).join("")}</select><select class="field" id="event-type"><option value="">Все события</option>${["snapshot", "connected", "disconnected"].map(x => `<option ${state.filters.type === x ? "selected" : ""}>${x}</option>`).join("")}</select><button class="button" id="event-filter">Применить</button></div>${panelTable(["Время", "Компьютер / SID", "Событие", "Решение", "Hardware hash", "Event ID"], rows)}${pagination(data)}`;
  document.getElementById("event-filter").onclick = () => { state.filters = { decision: document.getElementById("event-decision").value, type: document.getElementById("event-type").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderAlerts() {
  const data = await api("/identity-alerts", { limit: state.limit, offset: state.offset });
  const rows = data.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${badge(item.result)}</td><td>${formatDate(item.observed_at_utc)}</td><td>${esc(item.hostname)}</td><td>${esc((item.reasons || []).join(", "))}</td><td>${Math.round(item.confidence * 100)}%</td><td class="mono">${esc(item.candidate_physical_device_id)}</td></tr>`).join("");
  content.innerHTML = `${panelTable(["Тип", "Время", "Компьютер", "Основания", "Confidence", "Кандидат"], rows, "Коллизий и подозрений на клон нет")}${pagination(data)}`;
  bindRows(); bindPagination();
}

async function renderAudit() {
  const data = await api("/audit-log", { limit: state.limit, offset: state.offset, action: state.filters.action, success: state.filters.success });
  const rows = data.items.map(item => `<tr><td>${formatDate(item.created_at_utc)}</td><td><span class="primary">${esc(item.username)}</span><span class="secondary mono">${esc(item.source_ip)}</span></td><td>${esc(item.action)}</td><td><span class="badge ${item.success ? "same" : "alert"}">${item.success ? "SUCCESS" : "FAILED"}</span></td><td class="mono">${esc(JSON.stringify(item.details))}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><select class="field" id="audit-success"><option value="">Все результаты</option><option value="true" ${state.filters.success === "true" ? "selected" : ""}>Успешные</option><option value="false" ${state.filters.success === "false" ? "selected" : ""}>Неуспешные</option></select><input class="field search" id="audit-action" placeholder="Действие, например auth.login" value="${esc(state.filters.action || "")}"><button class="button" id="audit-filter">Применить</button></div>${panelTable(["Время", "Пользователь / IP", "Действие", "Результат", "Детали"], rows, "Записей аудита нет")}${pagination(data)}`;
  document.getElementById("audit-filter").onclick = () => { state.filters = { success: document.getElementById("audit-success").value, action: document.getElementById("audit-action").value.trim() }; state.offset = 0; render(); };
  bindPagination();
}

function detailItem(label, value, wide = false, mono = false) {
  return `<div class="detail-item ${wide ? "wide" : ""}"><label>${esc(label)}</label><div class="${mono ? "mono" : ""}">${esc(value)}</div></div>`;
}

async function openDevice(id) {
  openDrawer("USB-УСТРОЙСТВО", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/devices/${id}`);
    const title = [item.vendor, item.product].filter(Boolean).join(" ") || "Неизвестное устройство";
    const media = (item.media_states || []).map(x => `<div class="detail-item wide"><label>MEDIA STATE · ${formatDate(x.last_seen_at)}</label><div class="mono">identity ${esc(x.media_identity_sha256)}<br>state ${esc(x.media_state_sha256)}</div></div>`).join("");
    const computers = (item.used_on_computers || []).map(x => `<span class="badge info">${esc(x.hostname)}</span>`).join(" ") || "—";
    document.getElementById("drawer-title").textContent = title;
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Physical Device ID", item.id, true, true)}${detailItem("Статус", item.status)}${detailItem("Confidence", item.identity_confidence)}${detailItem("VID:PID", item.vid || item.pid ? `${item.vid}:${item.pid}` : "—")}${detailItem("Storage serial", item.storage_serial, false, true)}${detailItem("Hardware hash", item.hardware_stable_sha256, true, true)}<div class="detail-item wide"><label>Использовалась на ПК</label><div>${computers}</div></div>${detailItem("SID пользователей", (item.seen_user_sids || []).join(", "), true, true)}</div><h3 class="section-title">MEDIA STATES (${item.media_states.length})</h3><div class="detail-grid">${media || '<div class="empty">Нет данных</div>'}</div><h3 class="section-title">ИСХОДНЫЕ ПРИЗНАКИ</h3><pre class="json">${esc(JSON.stringify(item.representative_device, null, 2))}</pre>`;
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

async function openComputer(id) {
  openDrawer("КОМПЬЮТЕР", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/computers/${id}`);
    document.getElementById("drawer-title").textContent = item.hostname;
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Computer ID", item.id, true, true)}${detailItem("Домен", item.domain)}${detailItem("Последнее наблюдение", formatDate(item.last_seen_at))}</div><h3 class="section-title">ПОСЛЕДНИЕ СОБЫТИЯ</h3>${panelTable(["Время", "Тип", "Решение"], item.recent_observations.map(x => `<tr class="clickable" data-event="${esc(x.event_id)}"><td>${formatDate(x.observed_at_utc)}</td><td>${esc(x.event_type)}</td><td>${badge(x.identity_decision?.result)}</td></tr>`).join(""))}<h3 class="section-title">HOST DATA</h3><pre class="json">${esc(JSON.stringify(item.last_host, null, 2))}</pre>`;
    bindRows();
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

async function openEvent(id) {
  openDrawer("OBSERVATION", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/observations/${id}`);
    document.getElementById("drawer-title").textContent = item.hostname || "Observation";
    const decision = item.identity_decision || {};
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Event ID", item.event_id, true, true)}${detailItem("Время", formatDate(item.observed_at_utc))}${detailItem("Тип", item.event_type)}${detailItem("Решение", decision.result)}${detailItem("Confidence", decision.confidence != null ? `${Math.round(decision.confidence * 100)}%` : "—")}${detailItem("Physical Device ID", item.physical_device_id, true, true)}${detailItem("Основания", (decision.reasons || []).join(", "), true)}</div><h3 class="section-title">RAW OBSERVATION</h3><pre class="json">${esc(JSON.stringify(item.raw_observation, null, 2))}</pre>`;
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

async function openAgent(id) {
  openDrawer("АГЕНТ", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/agents/${id}`);
    document.getElementById("drawer-title").textContent = item.hostname;
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Agent ID", item.id, true, true)}${detailItem("Статус", item.status)}${detailItem("Версия", item.agent_version)}${detailItem("Домен", item.domain)}${detailItem("Размер очереди", item.queue_size)}${detailItem("Маршрут", item.selected_route)}${detailItem("Текущие IP", (item.current_ips || []).join(", "), true, true)}${detailItem("Source IP", item.source_ip, false, true)}${detailItem("Первый heartbeat", formatDate(item.first_seen_at_utc))}${detailItem("Последний heartbeat", formatDate(item.last_seen_at_utc))}</div>`;
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

function openDrawer(eyebrow, title, body) {
  document.getElementById("drawer-eyebrow").textContent = eyebrow;
  document.getElementById("drawer-title").textContent = title;
  document.getElementById("drawer-body").innerHTML = body;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); backdrop.hidden = false;
}

function closeDrawer() { drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); backdrop.hidden = true; }

function bindRows() {
  document.querySelectorAll("[data-device]").forEach(row => row.onclick = () => openDevice(row.dataset.device));
  document.querySelectorAll("[data-computer]").forEach(row => row.onclick = () => openComputer(row.dataset.computer));
  document.querySelectorAll("[data-event]").forEach(row => row.onclick = () => openEvent(row.dataset.event));
  document.querySelectorAll("[data-agent]").forEach(row => row.onclick = () => openAgent(row.dataset.agent));
}

async function render() {
  loading();
  document.getElementById("page-eyebrow").textContent = titles[state.page][0];
  document.getElementById("page-title").textContent = titles[state.page][1];
  document.querySelectorAll(".nav a").forEach(link => link.classList.toggle("active", link.dataset.page === state.page));
  try {
    if (state.page === "dashboard") await renderDashboard();
    if (state.page === "devices") await renderDevices();
    if (state.page === "computers") await renderComputers();
    if (state.page === "agents") await renderAgents();
    if (state.page === "events") await renderEvents();
    if (state.page === "alerts") await renderAlerts();
    if (state.page === "audit") await renderAudit();
  } catch (error) { showError(error); }
}

function route() {
  const requested = location.hash.replace("#", "") || "dashboard";
  const roleAllowed = requested !== "audit" || ["admin", "security"].includes(currentUser?.role);
  state.page = titles[requested] && roleAllowed ? requested : "dashboard";
  state.offset = 0; state.filters = {};
  document.getElementById("sidebar").classList.remove("open");
  render();
}

async function health() {
  const dot = document.getElementById("server-dot");
  const text = document.getElementById("server-status");
  try {
    const response = await fetch("/health/ready");
    if (!response.ok) throw new Error();
    dot.className = "status-dot ok"; text.textContent = "Доступен";
  } catch (_) { dot.className = "status-dot error"; text.textContent = "Недоступен"; }
}

document.getElementById("refresh-button").onclick = render;
document.getElementById("logout-button").onclick = async () => {
  const csrf = document.cookie.split("; ").find(item => item.startsWith("flashcontrol_csrf="));
  const token = csrf ? decodeURIComponent(csrf.split("=").slice(1).join("=")) : "";
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST", headers: { "X-CSRF-Token": token, Accept: "application/json" }
  });
  if (response.ok || response.status === 401) window.location.assign("/login");
};
document.getElementById("menu-button").onclick = () => document.getElementById("sidebar").classList.toggle("open");
document.getElementById("drawer-close").onclick = closeDrawer;
backdrop.onclick = closeDrawer;
document.addEventListener("keydown", event => { if (event.key === "Escape") closeDrawer(); });
window.addEventListener("hashchange", route);
setInterval(() => { document.getElementById("utc-clock").textContent = `UTC ${new Date().toISOString().slice(11, 19)}`; }, 1000);
setInterval(health, 30000);
api("/auth/me").then(user => {
  currentUser = user;
  document.querySelectorAll("[data-roles]").forEach(item => {
    item.hidden = !item.dataset.roles.split(",").includes(user.role);
  });
  document.getElementById("user-chip").textContent = `${user.username} · ${user.role}`;
  health(); route();
}).catch(showError);
