let state = {
  config: {},
  profiles: {},
  activeProfileId: "",
  selectedProfileId: "",
  sysInfo: { arch: "x64", os: "Desktop", gpu: "Hardware GPU", hwaccel: "Auto", edition: "Personal" },
  activeTab: "consoles",
  activeCat: 0,
  editingId: null,
  streamActive: false
};

function api() {
  return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
}

function showToast(msg, ms = 2600) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), ms);
}

function updateClock() {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  document.getElementById("clock").textContent = `${hh}:${mm}`;
}

async function initApp() {
  updateClock();
  setInterval(updateClock, 15000);

  if (!api()) {
    setTimeout(initApp, 100);
    return;
  }

  try {
    const data = await api().get_initial_data();
    state.config = data.config || data || {};
    state.profiles = state.config.profiles || {};
    state.activeProfileId = state.config.active_profile_id || Object.keys(state.profiles)[0] || "";
    state.selectedProfileId = state.activeProfileId;

    if (api().get_system_info) {
      state.sysInfo = await api().get_system_info();
    }
    const isPersonal = (state.sysInfo.edition || "").toLowerCase().includes("personal");
    const edBadge = document.getElementById("edition-badge");
    edBadge.textContent = isPersonal ? "PERSONAL" : "PUBLICA";
    edBadge.className = "pill " + (isPersonal ? "pill-personal" : "pill-public");

    document.getElementById("splash-sub").textContent =
      `Remote Play 2.0 • ${isPersonal ? "Edicion Personal" : "Edicion Publica"}`;
    document.getElementById("hw-badge").textContent = `${state.sysInfo.arch} • ${state.sysInfo.gpu}`;

    renderConsoles();
    renderSettings();
    refreshPadBadge();
    setInterval(refreshPadBadge, 5000);
  } catch (e) {
    console.error("Init error:", e);
  } finally {
    setTimeout(() => document.getElementById("splash").classList.add("hidden"), 450);
  }
}

async function refreshPadBadge() {
  if (!api() || !api().check_connected_controllers) return;
  try {
    const res = await api().check_connected_controllers();
    const list = res.controllers || [];
    const el = document.getElementById("pad-badge");
    el.textContent = list.length > 0 ? `Mando: ${list[0].name || "Conectado"}` : "Teclado / Mando";
  } catch (_) {}
}

function switchTab(tab) {
  state.activeTab = tab;
  document.getElementById("tab-consoles").classList.toggle("active", tab === "consoles");
  document.getElementById("tab-settings").classList.toggle("active", tab === "settings");
  document.getElementById("panel-consoles").classList.toggle("active", tab === "consoles");
  document.getElementById("panel-settings").classList.toggle("active", tab === "settings");
  if (tab === "settings") renderSettings();
  else renderConsoles();
}

function getResLabel(r) {
  switch (r) {
    case "2160p": return "4K (2160p) GPU";
    case "1440p": return "2K (1440p) GPU";
    case "1080p": return "1080p FHD";
    case "720p":  return "720p HD";
    default: return r || "1080p FHD";
  }
}

function getUpscaleLabel(m) {
  switch (m) {
    case "cas_high": return "Nitidez Alta";
    case "cas_med": return "Balanceado";
    case "direct": return "Directo";
    default: return "Auto 60FPS";
  }
}

function renderConsoles() {
  const row = document.getElementById("console-carousel");
  row.innerHTML = "";
  const ids = Object.keys(state.profiles);
  if (!state.selectedProfileId && ids.length > 0) state.selectedProfileId = ids[0];

  ids.forEach((id) => {
    const p = state.profiles[id];
    const isPs4 = (p.host_type || "").toUpperCase() === "PS4";
    const card = document.createElement("button");
    card.className = "console-card" + (id === state.selectedProfileId ? " selected" : "");
    card.innerHTML = `
      <img src="assets/devices/${isPs4 ? "ps4" : "ps5"}.png" alt="${isPs4 ? "PS4" : "PS5"}" />
      <div class="c-title">${escapeHtml(p.name || p.host_name || "PS5")}</div>
      <div class="c-sub">${escapeHtml(p.regist_key ? (p.local_ip || p.remote_ip || "Vinculada") : "Sin vincular")}</div>
    `;
    card.onclick = () => {
      state.selectedProfileId = id;
      state.activeProfileId = id;
      if (api().select_profile) api().select_profile(id);
      renderConsoles();
    };
    card.ondblclick = () => {
      if (p.regist_key) connectConsole(id, state.config.connection_mode || "auto");
      else openConsoleModal(id);
    };
    row.appendChild(card);
  });

  const addCard = document.createElement("button");
  addCard.className = "console-card";
  addCard.innerHTML = `
    <img src="assets/devices/unknown.png" alt="Agregar" />
    <div class="c-title">+ Agregar Consola</div>
    <div class="c-sub">LAN o Remoto (PIN)</div>
  `;
  addCard.onclick = () => openConsoleModal(null);
  row.appendChild(addCard);

  renderHero();
}

function renderHero() {
  const p = state.profiles[state.selectedProfileId];
  const cfg = state.config;
  const codecLbl = cfg.hdr ? "H.265 HDR" : (cfg.codec === "h264" ? "H.264" : "H.265");
  document.getElementById("hero-quality-pill").textContent =
    `${getResLabel(cfg.resolution)} • ${cfg.fps || 60} fps • ${codecLbl}`;

  const actions = document.getElementById("hero-actions");
  actions.innerHTML = "";

  if (!p) {
    document.getElementById("hero-title").textContent = "Sin consola seleccionada";
    document.getElementById("hero-sub").textContent = "Escanea tu red local o agrega una consola manualmente.";
    actions.appendChild(makeBtn("🔍 Buscar en Red (DDP)", true, () => scanConsoles()));
    actions.appendChild(makeBtn("+ Agregar Manual", false, () => openConsoleModal(null)));
    return;
  }

  const linked = !!(p.regist_key && p.rp_key);
  document.getElementById("hero-title").textContent = `${p.name || p.host_name || "PS5"} (${p.host_type || "PS5"})`;
  document.getElementById("hero-sub").textContent =
    `Local: ${p.local_ip || "—"}   |   Remota: ${p.remote_ip || "—"}   |   Estado: ${linked ? "Vinculada" : "Pendiente PIN"}`;

  if (linked) {
    actions.appendChild(makeBtn("▶ Conectar (Auto)", true, () => connectConsole(p.id, "auto")));
    if (p.local_ip) actions.appendChild(makeBtn("🏠 Local", false, () => connectConsole(p.id, "local")));
    if (p.remote_ip) actions.appendChild(makeBtn("🌐 Remoto", false, () => connectConsole(p.id, "remote")));
    actions.appendChild(makeBtn("⚡ Despertar", false, () => wakeupConsole(p)));
  } else {
    actions.appendChild(makeBtn("🔗 Vincular con PIN", true, () => openConsoleModal(p.id)));
  }
  actions.appendChild(makeBtn("⚙ Editar / Borrar", false, () => openConsoleModal(p.id)));
}

function makeBtn(label, primary, onClick) {
  const b = document.createElement("button");
  b.className = "btn" + (primary ? " btn-primary" : "");
  b.textContent = label;
  b.onclick = onClick;
  return b;
}

async function connectConsole(profileId, mode) {
  const p = state.profiles[profileId];
  if (!p) return;
  showToast(`Iniciando sesión (${mode.toUpperCase()})...`);
  try {
    if (api().set_profile_mode) await api().set_profile_mode(profileId, mode);
    const res = await api().launch_stream(profileId, {
      resolution: state.config.resolution || "1080p",
      fps: state.config.fps || 60,
      codec: state.config.codec || "hevc",
      hdr: !!state.config.hdr,
      bitrate_kbps: state.config.bitrate_kbps || 0,
      upscale_mode: state.config.upscale_mode || "auto",
      connection_mode: mode,
      audio_enabled: state.config.audio_enabled !== false,
      fullscreen: !!state.config.fullscreen
    });
    if (res && res.error) showToast("Error: " + res.error, 4000);
  } catch (e) {
    showToast("Error lanzando transmisión: " + e, 4000);
  }
}

async function wakeupConsole(p) {
  showToast("Enviando Wakeup DDP...");
  try {
    const ip = p.local_ip || p.remote_ip;
    const res = await api().wakeup_console(ip, p.id);
    showToast(res && res.success ? "Señal de encendido enviada" : "No se pudo enviar Wakeup");
  } catch (e) {
    showToast("Error Wakeup: " + e);
  }
}

async function scanConsoles() {
  showToast("Escaneando consolas PS5/PS4 en red local...");
  try {
    const res = await api().discover_consoles(3);
    const list = (res && res.consoles) ? res.consoles : (Array.isArray(res) ? res : []);
    if (!list.length) {
      showToast("No se encontraron consolas por DDP. Usa Agregar Manual.");
      return;
    }
    const c = list[0];
    const id = "prof_" + (c.host_id || Date.now());
    state.profiles[id] = {
      id,
      name: c.host_name || "PS5",
      host_name: c.host_name || "PS5",
      host_id: c.host_id || "",
      host_type: c.host_type || "PS5",
      local_ip: c.host_ip || "",
      remote_ip: "",
      connection_mode: "auto",
      status: c.status || "Detectada"
    };
    state.selectedProfileId = id;
    await api().save_profile(state.profiles[id]);
    renderConsoles();
    showToast(`Detectada: ${c.host_name || "PS5"} (${c.host_ip})`);
  } catch (e) {
    showToast("Error escaneando: " + e);
  }
}

/* Settings */
function renderSettings() {
  const cats = ["Transmisión", "Control", "Cuenta PSN y Remoto", "Registro", "Acerca de"];
  const catRow = document.getElementById("settings-cats");
  catRow.innerHTML = "";
  cats.forEach((c, idx) => {
    const b = document.createElement("button");
    b.className = "cat-btn" + (idx === state.activeCat ? " active" : "");
    b.textContent = c;
    b.onclick = () => { state.activeCat = idx; renderSettings(); };
    catRow.appendChild(b);
  });

  const list = document.getElementById("settings-list");
  list.innerHTML = "";
  const cfg = state.config;

  if (state.activeCat === 0) {
    addSettingRow(list, "Resolución / Reescalado GPU", "Reescalado hardware Metal/D3D11 a 2K y 4K a 60FPS", getResLabel(cfg.resolution), () => {
      const opts = ["720p", "1080p", "1440p", "2160p"];
      cfg.resolution = opts[(opts.indexOf(cfg.resolution || "1080p") + 1) % opts.length];
      persistSettings();
    });
    addSettingRow(list, "Motor de Reescalado GPU", "Auto optimiza 60FPS según tu GPU (M / Intel / ARM / x86)", getUpscaleLabel(cfg.upscale_mode), () => {
      const opts = ["auto", "cas_high", "cas_med", "direct"];
      cfg.upscale_mode = opts[(opts.indexOf(cfg.upscale_mode || "auto") + 1) % opts.length];
      persistSettings();
    });
    addSettingRow(list, "Velocidad (FPS)", "60 fps para fluidez máxima", `${cfg.fps || 60} fps`, () => {
      cfg.fps = (cfg.fps >= 60) ? 30 : 60;
      persistSettings();
    });
    addSettingRow(list, "Códec de Video", "H.265 recomendado para 1080p/2K/4K",
      cfg.hdr ? "H.265 HDR" : (cfg.codec === "h264" ? "H.264" : "H.265 (HEVC)"), () => {
      const cur = cfg.hdr ? "hevc_hdr" : (cfg.codec || "hevc");
      const opts = ["hevc", "hevc_hdr", "h264"];
      const nxt = opts[(opts.indexOf(cur) + 1) % opts.length];
      cfg.codec = nxt === "h264" ? "h264" : "hevc";
      cfg.hdr = nxt === "hevc_hdr";
      persistSettings();
    });
    addSettingRow(list, "Bitrate", "Mayor bitrate mejora nitidez en 2K/4K",
      !cfg.bitrate_kbps ? "Auto" : `${cfg.bitrate_kbps / 1000} Mbps`, () => {
      const vals = [0, 8000, 12000, 15000, 20000];
      cfg.bitrate_kbps = vals[(vals.indexOf(cfg.bitrate_kbps || 0) + 1) % vals.length];
      persistSettings();
    });
    addSettingRow(list, "Modo de Conexión", "Auto intenta Local y conmuta a IP Remota/Tailscale",
      cfg.connection_mode === "remote" ? "Solo Remoto" : (cfg.connection_mode === "local" ? "Solo Local" : "Auto (Local -> Remoto)"), () => {
      const opts = ["auto", "local", "remote"];
      cfg.connection_mode = opts[(opts.indexOf(cfg.connection_mode || "auto") + 1) % opts.length];
      persistSettings();
    });
    addSettingRow(list, "Audio Estéreo", "Opus 48kHz baja latencia", cfg.audio_enabled !== false ? "Activado" : "Desactivado", () => {
      cfg.audio_enabled = cfg.audio_enabled === false;
      persistSettings();
    });
    addSettingRow(list, "Pantalla Completa al iniciar", "Modo inmersivo sin bordes", cfg.fullscreen ? "Activado" : "Ventana", () => {
      cfg.fullscreen = !cfg.fullscreen;
      persistSettings();
    });
  } else if (state.activeCat === 1) {
    addSettingRow(list, "Botón Confirmar", "Intercambia Cruz y Círculo", cfg.circle_confirm ? "Círculo (◯)" : "Cruz (✕)", () => {
      cfg.circle_confirm = !cfg.circle_confirm;
      persistSettings();
    });
    addSettingRow(list, "Vibración (Rumble)", "Activa motores DualSense/Xbox", cfg.rumble !== false ? "Activado" : "Desactivado", () => {
      cfg.rumble = cfg.rumble === false;
      persistSettings();
    });
  } else if (state.activeCat === 2) {
    addSettingRow(list, "Vincular Cuenta PSN (OAuth)", "Obtiene tu Account ID oficial de PlayStation",
      cfg.psn_online_id || cfg.psn_account_id || "No vinculada", async () => {
      if (!api().start_psn_oauth) {
        showToast("Ingresa tu Account ID en Editar Consola");
        return;
      }
      showToast("Abriendo inicio de sesión PSN...");
      const res = await api().start_psn_oauth();
      if (res && res.success) {
        cfg.psn_account_id = res.account_id;
        cfg.psn_online_id = res.online_id || "PSN";
        persistSettings();
        showToast("Cuenta PSN vinculada: " + cfg.psn_online_id);
      } else if (res && res.error) {
        showToast("PSN: " + res.error);
      }
    });
    addSettingRow(list, "Escanear Consolas (DDP)", "Busca PS5/PS4 en la red local", "Escanear", () => scanConsoles());
  } else if (state.activeCat === 3) {
    const box = document.createElement("div");
    box.className = "log-box";
    box.textContent = "Cargando registros...";
    addSettingRow(list, "Limpiar Registros", "Limpia el log de sesión", "Limpiar", async () => {
      await api().clear_logs("launcher");
      box.textContent = "";
    });
    list.appendChild(box);
    api().get_logs("launcher", 200).then(r => {
      box.textContent = (r && r.lines) ? r.lines.join("\n") : (r && r.content ? r.content : "");
      box.scrollTop = box.scrollHeight;
    });
  } else {
    addSettingRow(list, "DRPS5 Versión", "Interfaz WebOS V2 Nativa para Escritorio", `2.0.0 (${state.sysInfo.edition})`, null);
    addSettingRow(list, "Arquitectura CPU", "Detección nativa Apple Silicon / Intel / x64 / ARM64", state.sysInfo.arch, null);
    addSettingRow(list, "Aceleración Gráfica", "Renderizador GPU para 2K/4K @ 60FPS", `${state.sysInfo.gpu} (${state.sysInfo.hwaccel})`, null);
  }
}

function addSettingRow(parent, title, desc, val, onClick) {
  const row = document.createElement("button");
  row.className = "setting-row" + (onClick ? " interactive" : "");
  row.innerHTML = `
    <div>
      <div class="s-title">${escapeHtml(title)}</div>
      <div class="s-desc">${escapeHtml(desc)}</div>
    </div>
    <div class="s-val">${escapeHtml(val)}</div>
  `;
  if (onClick) row.onclick = onClick;
  parent.appendChild(row);
}

async function persistSettings() {
  if (api() && api().save_settings) {
    await api().save_settings(state.config);
  }
  renderSettings();
  renderHero();
}

/* Console Modal */
function openConsoleModal(profileId) {
  state.editingId = profileId;
  const p = profileId ? state.profiles[profileId] : {};
  document.getElementById("f-name").value = p.name || "Mi PS5";
  document.getElementById("f-local").value = p.local_ip || "";
  document.getElementById("f-remote").value = p.remote_ip || "";
  document.getElementById("f-account").value = p.account_id || state.config.psn_account_id || "";
  document.getElementById("f-pin").value = "";
  document.getElementById("btn-del-console").style.display = profileId ? "inline-block" : "none";
  document.getElementById("modal-console").classList.add("open");
}

function closeConsoleModal() {
  document.getElementById("modal-console").classList.remove("open");
}

async function saveOrPairConsole() {
  const name = document.getElementById("f-name").value.trim() || "PS5";
  const localIp = document.getElementById("f-local").value.trim();
  const remoteIp = document.getElementById("f-remote").value.trim();
  const accId = document.getElementById("f-account").value.trim();
  const pin = document.getElementById("f-pin").value.trim();

  const id = state.editingId || ("prof_" + Date.now());
  const existing = state.profiles[id] || {};
  const prof = {
    ...existing,
    id,
    name,
    host_name: name,
    local_ip: localIp,
    remote_ip: remoteIp,
    account_id: accId,
    connection_mode: existing.connection_mode || "auto"
  };

  if (pin) {
    const targetIp = localIp || remoteIp;
    if (!targetIp || !accId) {
      showToast("Necesitas IP y Account ID para vincular con PIN");
      return;
    }
    showToast("Vinculando con " + targetIp + "...");
    const res = await api().pair_console(targetIp, pin, accId, id, prof.host_type || "PS5");
    if (res && res.success) {
      closeConsoleModal();
      const fresh = await api().get_profiles();
      state.profiles = fresh.profiles || fresh || state.profiles;
      state.selectedProfileId = id;
      renderConsoles();
      showToast("Consola vinculada correctamente");
    } else {
      showToast("Error vinculando: " + (res && res.error ? res.error : "Fallo"), 4000);
    }
  } else {
    await api().save_profile(prof);
    state.profiles[id] = prof;
    state.selectedProfileId = id;
    closeConsoleModal();
    renderConsoles();
    showToast("Perfil guardado");
  }
}

async function deleteEditingConsole() {
  if (!state.editingId) return;
  await api().delete_profile(state.editingId);
  delete state.profiles[state.editingId];
  state.selectedProfileId = Object.keys(state.profiles)[0] || "";
  closeConsoleModal();
  renderConsoles();
  showToast("Consola eliminada");
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

window.addEventListener("DOMContentLoaded", initApp);
