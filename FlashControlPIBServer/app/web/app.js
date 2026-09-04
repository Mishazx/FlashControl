"use strict";

const API = "/api/v1";
const titles = {
  dashboard: ["ЦЕНТР МОНИТОРИНГА", "Обзор"],
  devices: ["ИНВЕНТАРИЗАЦИЯ", "USB-устройства"],
  computers: ["ИНФРАСТРУКТУРА", "Компьютеры"],
  events: ["ЖУРНАЛ АУДИТА", "События"],
  alerts: ["IDENTITY ENGINE", "Предупреждения"],
  audit: ["БЕЗОПАСНОСТЬ", "Журнал действий"],
  users: ["АДМИНИСТРИРОВАНИЕ", "Пользователи"],
};
const state = { page: "dashboard", offset: 0, limit: 25, filters: {} };
let currentUser = null;
const content = document.getElementById("content");
const drawer = document.getElementById("drawer");
const backdrop = document.getElementById("drawer-backdrop");

const identityResultLabels = {
  SAME: "Совпадает",
  LIKELY_SAME: "Скорее совпадает",
  UNKNOWN: "Неизвестно",
  SERIAL_COLLISION: "Коллизия серийника",
  CLONE_SUSPECTED: "Подозрение на клон",
  DIFFERENT: "Другое устройство",
};

const confidenceLabels = {
  high: "Высокая",
  likely: "Вероятная",
  unknown: "Неизвестно",
};

const confidenceColumnHint = "Насколько система уверена, что это то же физическое устройство, а не похожая флешка с тем же серийником.";

const identityConfidenceHints = {
  high: "Высокая: железо и разметка совпали на том же компьютере, наблюдения склеены в одно устройство.",
  likely: "Вероятная: признаки похожи, но автоматически не склеивается — например, то же железо на другом ПК.",
  unknown: "Неизвестно: первое появление устройства или слишком мало совпадений.",
};

const decisionConfidenceHints = {
  SAME: "95%: то же железо, та же разметка и тот же компьютер.",
  LIKELY_SAME: "80%: то же железо и разметка, но другой компьютер.",
  UNKNOWN: "45%: железо совпало, разметка другая или отсутствует.",
  CLONE_SUSPECTED: "20%: разметка та же, железо другое — возможен клон.",
  SERIAL_COLLISION: "5%: серийник совпал, железо другое.",
  DIFFERENT: "0%: железо не совпало.",
};

const agentStatusLabels = {
  online: "Онлайн",
  offline: "Офлайн",
  missing: "Без агента",
};

const routeLabels = {
  direct: "Напрямую",
  proxy: "Через прокси",
  offline: "Офлайн",
};

const eventTypeLabels = {
  snapshot: "Снимок",
  connected: "Подключено",
  disconnected: "Отключено",
};

const deviceStatusLabels = {
  provisional: "Промежуточный",
};

const auditResultLabels = {
  true: "Успешно",
  false: "Неуспешно",
};

function translate(value, labels) {
  const key = value == null ? "" : String(value);
  return labels[key] || key || "Неизвестно";
}

function esc(value) {
  return String(value ?? "—").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);
}

function csrfToken() {
  const item = document.cookie.split("; ").find(value => value.startsWith("flashcontrol_csrf="));
  return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
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
  return `<span class="badge ${kind}">${esc(translate(value, identityResultLabels))}</span>`;
}

function canManageCleanup() {
  return ["admin", "security"].includes(currentUser?.role);
}

function canDeleteInventory() {
  return currentUser?.role === "admin";
}

async function apiRequest(path, { method = "GET", params = {}, body, headers = {} } = {}) {
  const url = new URL(API + path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, value);
  });
  const requestHeaders = { Accept: "application/json", ...headers };
  const options = { method, headers: requestHeaders };
  if (method !== "GET") {
    requestHeaders["X-CSRF-Token"] = csrfToken();
  }
  if (body !== undefined) {
    requestHeaders["Content-Type"] = "application/json";
    options.body = typeof body === "string" ? body : JSON.stringify(body);
  }
  const response = await fetch(url, options);
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

async function api(path, params = {}) {
  return apiRequest(path, { params });
}

async function destructiveAction(path, message) {
  if (!window.confirm(message)) return false;
  await apiRequest(path, { method: "DELETE" });
  return true;
}

function clearDrawerDelete() {
  const button = document.getElementById("drawer-delete");
  button.hidden = true;
  button.onclick = null;
}

function bindDrawerDelete(enabled, path, message) {
  const button = document.getElementById("drawer-delete");
  if (!enabled) {
    clearDrawerDelete();
    return;
  }
  button.hidden = false;
  button.onclick = async () => {
    try {
      if (!await destructiveAction(path, message)) return;
      closeDrawer();
      await render();
    } catch (error) {
      showError(error);
    }
  };
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

function hintAttr(text) {
  return text ? ` class="hint" title="${esc(text)}"` : "";
}

function confidenceBadge(level) {
  const kind = level === "high" ? "same" : level === "likely" ? "info" : "warning";
  const hint = identityConfidenceHints[level] || identityConfidenceHints.unknown;
  return `<span class="badge ${kind} hint" title="${esc(hint)}">${esc(translate(level, confidenceLabels))}</span>`;
}

function decisionConfidence(result, confidence) {
  const percent = confidence != null ? `${Math.round(confidence * 100)}%` : "—";
  const hint = decisionConfidenceHints[result] || confidenceColumnHint;
  return `<span class="hint" title="${esc(hint)}">${esc(percent)}</span>`;
}

function headerCell(header) {
  if (header && typeof header === "object") {
    return `<th${hintAttr(header.title)}>${esc(header.label)}</th>`;
  }
  return `<th>${esc(header)}</th>`;
}

function panelTable(headers, rows, emptyText = "Данных пока нет") {
  return `<div class="panel"><div class="table-wrap"><table><thead><tr>${headers.map(headerCell).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="empty">${esc(emptyText)}</td></tr>`}</tbody></table></div></div>`;
}

function pagination(data) {
  const start = data.total ? data.offset + 1 : 0;
  const end = Math.min(data.offset + data.items.length, data.total);
  return `<div class="pagination"><span>${start}–${end} из ${data.total}</span><div><button type="button" class="button ghost" data-page-offset="${Math.max(0, data.offset - data.limit)}" ${data.offset === 0 ? "disabled" : ""}>Назад</button> <button type="button" class="button ghost" data-page-offset="${data.offset + data.limit}" ${end >= data.total ? "disabled" : ""}>Далее</button></div></div>`;
}

function bindPagination() {
  if (content.dataset.paginationBound === "1") return;
  content.dataset.paginationBound = "1";
  content.addEventListener("click", event => {
    const button = event.target.closest("[data-page-offset]");
    if (!button || button.disabled || !content.contains(button)) return;
    event.preventDefault();
    state.offset = Number(button.dataset.pageOffset);
    render();
  });
}

async function renderDashboard() {
  const [stats, alerts, events] = await Promise.all([
    api("/dashboard"), api("/identity-alerts", { limit: 5 }), api("/observations", { limit: 6 })
  ]);
  const metrics = [
    ["Компьютеры", stats.computers], ["Физические устройства", stats.physical_devices],
    ["Наблюдения", stats.observations], ["Media states", stats.media_states],
    ["Компьютеры онлайн", `${stats.agents_online}/${stats.computers}`],
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
  const rows = data.items.map(item => `<tr class="clickable" data-device="${esc(item.id)}"><td><span class="primary">${esc([item.vendor, item.product].filter(Boolean).join(" ") || "Неизвестное устройство")}</span><span class="secondary mono">${esc(item.id)}</span></td><td>${item.vid || item.pid ? `${esc(item.vid)}:${esc(item.pid)}` : "—"}</td><td class="mono">${esc(item.storage_serial)}</td><td>${shortHash(item.hardware_stable_sha256)}</td><td>${confidenceBadge(item.identity_confidence)}</td><td>${formatDate(item.last_seen_at)}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="device-hash" placeholder="Полный hardware hash" value="${esc(state.filters.hash || "")}"><select class="field" id="device-status"><option value="">Все статусы</option><option value="provisional" ${state.filters.status === "provisional" ? "selected" : ""}>${esc(translate("provisional", deviceStatusLabels))}</option></select><button class="button" id="device-filter">Применить</button></div>${panelTable(["Устройство", "VID:PID", "Storage serial", "Hardware hash", { label: "Confidence", title: confidenceColumnHint }, "Последнее наблюдение"], rows)}${pagination(data)}`;
  document.getElementById("device-filter").onclick = () => { state.filters = { hash: document.getElementById("device-hash").value.trim(), status: document.getElementById("device-status").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderComputers() {
  const data = await api("/computers", { limit: state.limit, offset: state.offset, hostname: state.filters.hostname, agent_status: state.filters.agent_status });
  const rows = data.items.map(item => {
    const agent = item.agent;
    const status = agent ? `<span class="badge ${agent.status === "online" ? "same" : "alert"}">${esc(translate(agent.status, agentStatusLabels))}</span>` : '<span class="badge warning">НЕ УСТАНОВЛЕН</span>';
    const queue = agent?.queue_size ? `<span class="badge warning">${agent.queue_size}</span>` : (agent ? "0" : "—");
    return `<tr class="clickable" data-computer="${esc(item.id)}"><td><span class="primary">${esc(item.hostname)}</span><span class="secondary mono">${esc(item.id)}</span></td><td>${esc(item.domain)}</td><td>${status}</td><td>${queue}</td><td>${esc(translate(agent?.selected_route, routeLabels))}</td><td>${formatDate(agent?.last_seen_at_utc || item.last_seen_at)}</td></tr>`;
  }).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="computer-search" placeholder="Имя компьютера" value="${esc(state.filters.hostname || "")}"><select class="field" id="computer-agent-status"><option value="">Все состояния</option><option value="online" ${state.filters.agent_status === "online" ? "selected" : ""}>${esc(translate("online", agentStatusLabels))}</option><option value="offline" ${state.filters.agent_status === "offline" ? "selected" : ""}>${esc(translate("offline", agentStatusLabels))}</option><option value="missing" ${state.filters.agent_status === "missing" ? "selected" : ""}>${esc(translate("missing", agentStatusLabels))}</option></select><button class="button" id="computer-filter">Применить</button></div>${panelTable(["Компьютер", "Домен", "Статус", "Очередь", "Маршрут", "Последняя связь"], rows)}${pagination(data)}`;
  document.getElementById("computer-filter").onclick = () => { state.filters = { hostname: document.getElementById("computer-search").value.trim(), agent_status: document.getElementById("computer-agent-status").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderEvents() {
  const data = await api("/observations", { limit: state.limit, offset: state.offset, event_type: state.filters.type, decision: state.filters.decision });
  const rows = data.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${formatDate(item.observed_at_utc)}</td><td><span class="primary">${esc(item.hostname)}</span><span class="secondary">${esc(item.user_sid)}</span></td><td>${esc(translate(item.event_type, eventTypeLabels))}</td><td>${badge(item.identity_decision?.result)}</td><td>${shortHash(item.hardware_stable_sha256)}</td><td class="mono">${esc(item.event_id)}</td></tr>`).join("");
  const decisions = ["SAME", "LIKELY_SAME", "UNKNOWN", "SERIAL_COLLISION", "CLONE_SUSPECTED", "DIFFERENT"];
  content.innerHTML = `<div class="toolbar"><select class="field" id="event-decision"><option value="">Все решения</option>${decisions.map(x => `<option ${state.filters.decision === x ? "selected" : ""}>${esc(translate(x, identityResultLabels))}</option>`).join("")}</select><select class="field" id="event-type"><option value="">Все события</option>${["snapshot", "connected", "disconnected"].map(x => `<option ${state.filters.type === x ? "selected" : ""}>${esc(translate(x, eventTypeLabels))}</option>`).join("")}</select><button class="button" id="event-filter">Применить</button></div>${panelTable(["Время", "Компьютер / SID", "Событие", "Решение", "Hardware hash", "Event ID"], rows)}${pagination(data)}`;
  document.getElementById("event-filter").onclick = () => { state.filters = { decision: document.getElementById("event-decision").value, type: document.getElementById("event-type").value }; state.offset = 0; render(); };
  bindRows(); bindPagination();
}

async function renderAlerts() {
  const data = await api("/identity-alerts", { limit: state.limit, offset: state.offset });
  const rows = data.items.map(item => `<tr class="clickable" data-event="${esc(item.event_id)}"><td>${badge(item.result)}</td><td>${formatDate(item.observed_at_utc)}</td><td>${esc(item.hostname)}</td><td>${esc((item.reasons || []).join(", "))}</td><td>${decisionConfidence(item.result, item.confidence)}</td><td class="mono">${esc(item.candidate_physical_device_id)}</td></tr>`).join("");
  content.innerHTML = `${panelTable(["Тип", "Время", "Компьютер", "Основания", { label: "Confidence", title: confidenceColumnHint }, "Кандидат"], rows, "Коллизий и подозрений на клон нет")}${pagination(data)}`;
  bindRows(); bindPagination();
}

async function renderAudit() {
  const data = await api("/audit-log", { limit: state.limit, offset: state.offset, action: state.filters.action, success: state.filters.success });
  const rows = data.items.map(item => `<tr><td>${formatDate(item.created_at_utc)}</td><td><span class="primary">${esc(item.username)}</span><span class="secondary mono">${esc(item.source_ip)}</span></td><td>${esc(item.action)}</td><td><span class="badge ${item.success ? "same" : "alert"}">${esc(translate(String(item.success), auditResultLabels))}</span></td><td class="mono">${esc(JSON.stringify(item.details))}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><select class="field" id="audit-success"><option value="">Все результаты</option><option value="true" ${state.filters.success === "true" ? "selected" : ""}>Успешные</option><option value="false" ${state.filters.success === "false" ? "selected" : ""}>Неуспешные</option></select><input class="field search" id="audit-action" placeholder="Действие, например auth.login" value="${esc(state.filters.action || "")}"><button class="button" id="audit-filter">Применить</button></div>${panelTable(["Время", "Пользователь / IP", "Действие", "Результат", "Детали"], rows, "Записей аудита нет")}${pagination(data)}`;
  document.getElementById("audit-filter").onclick = () => { state.filters = { success: document.getElementById("audit-success").value, action: document.getElementById("audit-action").value.trim() }; state.offset = 0; render(); };
  bindPagination();
}

function roleLabel(role) {
  return ({ admin: "Администратор", security: "Безопасность", auditor: "Аудитор" })[role] || role;
}

async function renderUsers() {
  const data = await api("/users", { q: state.filters.q });
  const rows = data.items.map(user => `<tr class="clickable" data-user="${esc(user.id)}"><td><span class="primary">${esc(user.username)}</span><span class="secondary">${user.is_local ? "Локальная учётная запись" : "Учётная запись LDAP"}</span></td><td><span class="badge info">${esc(roleLabel(user.role))}</span></td><td><span class="badge ${user.enabled ? "same" : "alert"}">${user.enabled ? "Активен" : "Отключён"}</span></td><td>${user.active_sessions || "—"}</td><td>${formatDate(user.last_login_at_utc)}</td><td>${formatDate(user.created_at_utc)}</td></tr>`).join("");
  content.innerHTML = `<div class="toolbar"><input class="field search" id="user-search" placeholder="Поиск по логину" value="${esc(state.filters.q || "")}"><button class="button" id="user-filter">Найти</button><button class="button push-right" id="new-user">Добавить пользователя</button></div>${panelTable(["Пользователь", "Роль", "Статус", "Сессии", "Последний вход", "Создан"], rows, "Пользователи не найдены")}`;
  document.getElementById("user-filter").onclick = () => { state.filters = { q: document.getElementById("user-search").value.trim() }; render(); };
  document.getElementById("user-search").onkeydown = event => { if (event.key === "Enter") document.getElementById("user-filter").click(); };
  document.getElementById("new-user").onclick = openCreateUser;
  document.querySelectorAll("[data-user]").forEach(row => row.onclick = () => openUser(row.dataset.user, data.items.find(user => String(user.id) === row.dataset.user)));
}

function userFormOptions(selected) {
  return ["admin", "security", "auditor"].map(role => `<option value="${role}" ${role === selected ? "selected" : ""}>${esc(roleLabel(role))}</option>`).join("");
}

function openCreateUser() {
  openDrawer("ПОЛЬЗОВАТЕЛИ", "Новый пользователь", `<form class="user-form" id="user-create-form"><label>Логин<input class="field" name="username" required maxlength="128" autocomplete="username"></label><label>Роль<select class="field" name="role">${userFormOptions("auditor")}</select></label><label class="wide">Пароль<input class="field" name="password" type="password" required minlength="12" autocomplete="new-password"><small>Не менее 12 символов</small></label><div class="drawer-actions wide"><button class="button" type="submit">Создать пользователя</button></div></form>`);
  document.getElementById("user-create-form").onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiRequest("/users", { method: "POST", body: Object.fromEntries(form) });
      closeDrawer(); await render();
    } catch (error) { showDrawerError(error); }
  };
}

function showDrawerError(error) {
  const box = document.getElementById("user-form-error");
  if (box) box.textContent = error.message;
  else showError(error);
}

function openUser(id, user) {
  if (!user) return;
  openDrawer("ПОЛЬЗОВАТЕЛИ", user.username, `<form class="user-form" id="user-update-form"><p class="form-error" id="user-form-error"></p><label>Роль<select class="field" name="role">${userFormOptions(user.role)}</select></label><label>Статус<select class="field" name="enabled"><option value="true" ${user.enabled ? "selected" : ""}>Активен</option><option value="false" ${!user.enabled ? "selected" : ""}>Отключён</option></select></label>${user.is_local ? '<label class="wide">Новый пароль <span class="optional">(необязательно)</span><input class="field" name="password" type="password" minlength="12" autocomplete="new-password"><small>После смены пароля все сессии пользователя будут завершены.</small></label>' : '<div class="form-note wide">Роль учётной записи LDAP обновляется при следующем входе согласно настройкам Active Directory.</div>'}<div class="drawer-actions wide"><button class="button" type="submit">Сохранить изменения</button></div></form>`);
  document.getElementById("user-update-form").onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = { role: form.get("role"), enabled: form.get("enabled") === "true" };
    if (form.get("password")) body.password = form.get("password");
    try {
      await apiRequest(`/users/${id}`, { method: "PATCH", body });
      closeDrawer(); await render();
    } catch (error) { showDrawerError(error); }
  };
}

function detailItem(label, value, wide = false, mono = false, title = "") {
  return `<div class="detail-item ${wide ? "wide" : ""}"><label${hintAttr(title)}>${esc(label)}</label><div class="${mono ? "mono" : ""}">${esc(value)}</div></div>`;
}

async function openDevice(id) {
  openDrawer("USB-УСТРОЙСТВО", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/devices/${id}`);
    const title = [item.vendor, item.product].filter(Boolean).join(" ") || "Неизвестное устройство";
    const media = (item.media_states || []).map(x => `<div class="detail-item wide"><label>MEDIA STATE · ${formatDate(x.last_seen_at)}</label><div class="mono">identity ${esc(x.media_identity_sha256)}<br>state ${esc(x.media_state_sha256)}</div></div>`).join("");
    const computers = (item.used_on_computers || []).map(x => `<span class="badge info">${esc(x.hostname)}</span>`).join(" ") || "—";
    document.getElementById("drawer-title").textContent = title;
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Physical Device ID", item.id, true, true)}${detailItem("Статус", translate(item.status, deviceStatusLabels))}${detailItem("Confidence", translate(item.identity_confidence, confidenceLabels), false, false, identityConfidenceHints[item.identity_confidence] || confidenceColumnHint)}${detailItem("VID:PID", item.vid || item.pid ? `${item.vid}:${item.pid}` : "—")}${detailItem("Storage serial", item.storage_serial, false, true)}${detailItem("Hardware hash", item.hardware_stable_sha256, true, true)}<div class="detail-item wide"><label>Использовалась на ПК</label><div>${computers}</div></div>${detailItem("SID пользователей", (item.seen_user_sids || []).join(", "), true, true)}</div><h3 class="section-title">MEDIA STATES (${item.media_states.length})</h3><div class="detail-grid">${media || '<div class="empty">Нет данных</div>'}</div><h3 class="section-title">ИСХОДНЫЕ ПРИЗНАКИ</h3><pre class="json">${esc(JSON.stringify(item.representative_device, null, 2))}</pre>`;
    bindDrawerDelete(
      canDeleteInventory(),
      `/devices/${id}`,
      "Удалить USB-устройство и все связанные с ним события?",
    );
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

async function openComputer(id) {
  openDrawer("КОМПЬЮТЕР", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/computers/${id}`);
    document.getElementById("drawer-title").textContent = item.hostname;
    const agent = item.agent;
    const agentDetails = agent ? `${detailItem("Статус агента", translate(agent.status, agentStatusLabels))}${detailItem("Версия агента", agent.agent_version)}${detailItem("Agent ID", agent.id, true, true)}${detailItem("Размер очереди", agent.queue_size)}${detailItem("Маршрут", translate(agent.selected_route, routeLabels))}${detailItem("Текущие IP", (agent.current_ips || []).join(", "), true, true)}${detailItem("Последний heartbeat", formatDate(agent.last_seen_at_utc))}` : detailItem("Агент", "Не зарегистрирован", true);
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Computer ID", item.id, true, true)}${detailItem("Домен", item.domain)}${detailItem("Последнее наблюдение", formatDate(item.last_seen_at))}${agentDetails}</div><h3 class="section-title">ПОСЛЕДНИЕ СОБЫТИЯ</h3>${panelTable(["Время", "Тип", "Решение"], item.recent_observations.map(x => `<tr class="clickable" data-event="${esc(x.event_id)}"><td>${formatDate(x.observed_at_utc)}</td><td>${esc(translate(x.event_type, eventTypeLabels))}</td><td>${badge(x.identity_decision?.result)}</td></tr>`).join(""))}<h3 class="section-title">HOST DATA</h3><pre class="json">${esc(JSON.stringify(item.last_host, null, 2))}</pre>`;
    bindDrawerDelete(
      canDeleteInventory(),
      `/computers/${id}`,
      "Удалить компьютер и все связанные с ним события?",
    );
    bindRows();
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

async function openEvent(id) {
  openDrawer("OBSERVATION", "Загрузка…", '<div class="loading"><div class="spinner"></div></div>');
  try {
    const item = await api(`/observations/${id}`);
    document.getElementById("drawer-title").textContent = item.hostname || "Observation";
    const decision = item.identity_decision || {};
    document.getElementById("drawer-body").innerHTML = `<div class="detail-grid">${detailItem("Event ID", item.event_id, true, true)}${detailItem("Время", formatDate(item.observed_at_utc))}${detailItem("Тип", translate(item.event_type, eventTypeLabels))}${detailItem("Решение", translate(decision.result, identityResultLabels))}${detailItem("Confidence", decision.confidence != null ? `${Math.round(decision.confidence * 100)}%` : "—", false, false, decisionConfidenceHints[decision.result] || confidenceColumnHint)}${detailItem("Physical Device ID", item.physical_device_id, true, true)}${detailItem("Основания", (decision.reasons || []).join(", "), true)}</div><h3 class="section-title">RAW OBSERVATION</h3><pre class="json">${esc(JSON.stringify(item.raw_observation, null, 2))}</pre>`;
    bindDrawerDelete(
      canManageCleanup(),
      `/observations/${id}`,
      "Удалить событие наблюдения?",
    );
  } catch (error) { document.getElementById("drawer-body").innerHTML = `<div class="empty">${esc(error.message)}</div>`; }
}

function openDrawer(eyebrow, title, body) {
  clearDrawerDelete();
  document.getElementById("drawer-eyebrow").textContent = eyebrow;
  document.getElementById("drawer-title").textContent = title;
  document.getElementById("drawer-body").innerHTML = body;
  drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false"); backdrop.hidden = false;
}

function closeDrawer() {
  clearDrawerDelete();
  drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); backdrop.hidden = true;
}

function bindRows() {
  document.querySelectorAll("[data-device]").forEach(row => row.onclick = () => openDevice(row.dataset.device));
  document.querySelectorAll("[data-computer]").forEach(row => row.onclick = () => openComputer(row.dataset.computer));
  document.querySelectorAll("[data-event]").forEach(row => row.onclick = () => openEvent(row.dataset.event));
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
    if (state.page === "events") await renderEvents();
    if (state.page === "alerts") await renderAlerts();
    if (state.page === "audit") await renderAudit();
    if (state.page === "users") await renderUsers();
  } catch (error) { showError(error); }
}

function route() {
  const requested = location.hash.replace("#", "") || "dashboard";
  const roleAllowed = (requested !== "audit" || ["admin", "security"].includes(currentUser?.role)) && (requested !== "users" || currentUser?.role === "admin");
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
