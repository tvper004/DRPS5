/* ==========================================================================
   DRPS5 - Frontend Controller
   Gestión integral de Perfiles PS5, Red Local e Internet Remoto y Streaming
   ========================================================================== */

let currentConfig = {};
let allProfiles = [];
let activeProfile = null;

// Si hay datos semilla embebidos en el HTML (Personal o Público), cargarlos de inmediato
if (typeof window !== 'undefined' && window.__INITIAL_DATA__) {
  try {
    const initSeed = window.__INITIAL_DATA__;
    if (initSeed && initSeed.profiles && initSeed.profiles.length > 0) {
      currentConfig = initSeed.config || initSeed;
      allProfiles = initSeed.profiles || [];
      activeProfile = initSeed.active_profile || allProfiles[0];
      const applySeedNow = () => {
        if (typeof applyConfigToUI === 'function') applyConfigToUI(currentConfig);
        if (typeof renderProfileSelect === 'function') renderProfileSelect(allProfiles, initSeed.active_profile_id || (activeProfile ? activeProfile.id : ''));
        if (typeof applyProfileToUI === 'function') applyProfileToUI(activeProfile);
      };
      if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', applySeedNow);
      } else {
        setTimeout(applySeedNow, 10);
      }
    }
  } catch(e) {}
}

// Si estamos en Android, conectar inmediatamente con el puente nativo DRPS5Native
if (typeof window !== 'undefined' && window.DRPS5Native) {
  const methods = [
    'get_initial_data','get_profiles','save_profile','delete_profile','select_profile',
    'set_profile_mode','update_profile_remote_ip','discover_consoles','wakeup_console',
    'pair_console','launch_stream','save_settings','get_logs','clear_logs','purge_old_logs',
    'open_log_folder','get_gamepad_mapping','save_gamepad_mapping',
    'get_bluetooth_devices','start_bluetooth_scan','stop_bluetooth_scan','pair_bluetooth_device',
    'unpair_bluetooth_device','connect_bluetooth_device'
  ];
  const apiObj = {};
  methods.forEach(m => {
    apiObj[m] = function(...args) {
      return new Promise(resolve => {
        try {
          const raw = window.DRPS5Native.invoke(m, JSON.stringify(args || []));
          resolve(raw ? JSON.parse(raw) : {});
        } catch(e) {
          resolve({ success: false, error: String(e) });
        }
      });
    };
  });
  window.pywebview = { api: apiObj };
} else if (!window.pywebview && typeof window !== 'undefined' && !window.DRPS5Native) {
  // Soporte multiplataforma webOS / Browser para servicio local en 127.0.0.1:8085
  const methods = [
    'get_initial_data','get_profiles','save_profile','delete_profile','select_profile',
    'set_profile_mode','update_profile_remote_ip','discover_consoles','wakeup_console',
    'pair_console','launch_stream','save_settings','get_logs','clear_logs','purge_old_logs',
    'open_log_folder','get_gamepad_mapping','save_gamepad_mapping',
    'get_bluetooth_devices','start_bluetooth_scan','stop_bluetooth_scan','pair_bluetooth_device',
    'unpair_bluetooth_device','connect_bluetooth_device'
  ];
  const apiObj = {};
  methods.forEach(m => {
    apiObj[m] = async function(...args) {
      try {
        const res = await fetch(`http://127.0.0.1:8085/api/${m}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(args)
        });
        return await res.json();
      } catch (e) {
        console.warn(`API call fallback failed for ${m}:`, e);
        return { success: false, error: String(e) };
      }
    };
  });
  window.pywebview = { api: apiObj };

  // Despertar el servicio de backend webOS a través de Luna
  if (typeof webOS !== 'undefined' && webOS.service && typeof webOS.service.request === 'function') {
    try {
      webOS.service.request('luna://com.drps5.remoteplay.service', {
        method: 'status',
        parameters: {},
        onSuccess: function() { console.log('DRPS5 webOS Backend despierto vía Luna'); },
        onFailure: function() {}
      });
    } catch(e) {}
  }

  window.addEventListener('DOMContentLoaded', () => {
    setTimeout(initDRPS5, 120);
  });
}

// Navegación con mando a distancia webOS (Botón Atrás = 461), Teclado y Mandos
window.addEventListener('keydown', (e) => {
  if (e.keyCode === 461 || e.key === 'GoBack' || e.key === 'Escape') {
    if (window.isStreamFullscreenActive) {
      closeStreamFullscreen();
      e.preventDefault();
      return;
    }
    if (window._isGamepadTestingActive) {
      stopGamepadTestTimer(true);
      e.preventDefault();
      return;
    }
    if (document.querySelector('.modal-overlay.active')) {
      if (typeof closeAllModals === 'function') closeAllModals();
      e.preventDefault();
    } else {
      const activeTab = document.querySelector('.tab-content.active');
      if (activeTab && activeTab.id !== 'tab-stream') {
        switchTab('stream');
        e.preventDefault();
      }
    }
  } else if (window.isStreamFullscreenActive) {
    if (typeof resetStreamHudTimer === 'function') resetStreamHudTimer();
  }
});

// --------------------------------------------------------------------------
// 1. Inicialización y Carga de Perfiles
// --------------------------------------------------------------------------
let drps5Initialized = false;
let initRetryCount = 0;

async function initDRPS5() {
  if (drps5Initialized) return;
  if (!window.pywebview || !window.pywebview.api) return;

  setMsg("Inicializando motor DRPS5 y cargando perfiles...");
  try {
    if (window.DRPS5Native || /Android/i.test(navigator.userAgent)) {
      const macBtn = document.getElementById("btn-macos-game-shortcuts");
      if (macBtn) macBtn.style.display = "none";
      document.querySelectorAll(".btn-log-folder").forEach(el => {
        el.style.display = "none";
      });
    }

    const data = await window.pywebview.api.get_initial_data();
    if (data && data.success !== false && data.profiles && data.profiles.length > 0) {
      drps5Initialized = true;
      currentConfig = data.config || {};
      applyConfigToUI(currentConfig);

      allProfiles = data.profiles || [];
      activeProfile = data.active_profile || (allProfiles.length > 0 ? allProfiles[0] : null);

      renderProfileSelect(allProfiles, data.active_profile_id);
      applyProfileToUI(activeProfile);
    } else {
      // Reintentar si el servicio en webOS aún está iniciando
      if (!drps5Initialized && initRetryCount < 25) {
        initRetryCount++;
        setTimeout(initDRPS5, 400);
        return;
      }
    }
  } catch (err) {
    console.error("Error al cargar datos iniciales:", err);
    if (!drps5Initialized && initRetryCount < 25) {
      initRetryCount++;
      setTimeout(initDRPS5, 400);
      return;
    }
  }

  // Cargar mapeo de mando guardado
  try {
    const gpData = await window.pywebview.api.get_gamepad_mapping();
    if (gpData && gpData.mapping) {
      currentGamepadMapping = Object.assign(currentGamepadMapping, gpData.mapping);
      updateMappingBadges();
    }
  } catch (e) {
    console.warn("No se pudo cargar mapeo de mando:", e);
  }

  // Iniciar navegación global por mando
  if (typeof initGlobalGamepadNavigator === 'function') {
    initGlobalGamepadNavigator();
  }

  // Monitor de mandos conectados en tiempo real
  pollConnectedControllers();
  setInterval(pollConnectedControllers, 1500);

  // Cerrar cualquier modal que pudiera haber quedado en caché del navegador
  closeAllModals();

  // Seleccionar por defecto el botón de iniciar pantalla remota
  setTimeout(() => {
    const launchBtn = document.getElementById('btn-launch-stream');
    if (launchBtn) launchBtn.focus();
  }, 250);

  // Escaneo automático silencioso en segundo plano tras 1s
  setTimeout(silentScan, 1000);
}

window.addEventListener('pywebviewready', initDRPS5);
if (window.pywebview && window.pywebview.api) {
  initDRPS5();
} else {
  const initCheckTimer = setInterval(() => {
    if (window.pywebview && window.pywebview.api) {
      clearInterval(initCheckTimer);
      initDRPS5();
    }
  }, 100);
  setTimeout(() => clearInterval(initCheckTimer), 6000);
}

// Control de Panel Lateral (Sidebar contraíble por defecto)
function toggleSidebar(forceState) {
  const sidebar = document.getElementById('app-sidebar');
  if (!sidebar) return;
  if (typeof forceState === 'boolean') {
    sidebar.classList.toggle('collapsed', !forceState);
  } else {
    sidebar.classList.toggle('collapsed');
  }
}

function selectTab(tabId) {
  switchTab(tabId);
  // Auto-contraer en pantallas de TV / APK o táctiles tras seleccionar
  toggleSidebar(false);
}

// Cambiar de pestaña principal
function switchTab(tabId) {
  document.querySelectorAll('.nav-pill').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
  if (typeof closeAllModals === 'function') closeAllModals();

  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  const activeContent = document.getElementById(`tab-${tabId}`);

  if (activeBtn) activeBtn.classList.add('active');
  if (activeContent) activeContent.classList.add('active');

  // Si salimos de la pestaña de mando y la prueba estaba activa, detenerla para liberar el mando
  if (tabId !== 'gamepad' && window._isGamepadTestingActive) {
    if (typeof stopGamepadTestTimer === 'function') stopGamepadTestTimer(true);
  }

  // Si cambiamos a vincular, sincronizar datos del perfil activo
  if (tabId === 'pair' && activeProfile) {
    syncPairTab(activeProfile);
  }
  if (tabId === 'stream') {
    setTimeout(() => {
      const launchBtn = document.getElementById('btn-launch-stream');
      if (launchBtn) launchBtn.focus();
    }, 100);
  }
  // Si cambiamos a logs, cargar registros en vivo
  if (tabId === 'logs') {
    loadLogs();
  }
  // Si cambiamos a calibración de mando, iniciar bucle visualizador
  if (tabId === 'gamepad') {
    setupGamepadButtonsGrid();
    updateMappingBadges();
    if (gamepadPollRaf) {
      clearTimeout(gamepadPollRaf);
      gamepadPollRaf = null;
    }
    gamepadPollRaf = setTimeout(pollGamepadLoop, 30);
  }
  // Si cambiamos a Bluetooth TV, cargar estado de adaptador y lista de dispositivos
  if (tabId === 'bluetooth') {
    loadBluetoothDevices();
  }
}

// --------------------------------------------------------------------------
// 2. Renderizado y Gestión de Perfiles
// --------------------------------------------------------------------------
function renderProfileSelect(profiles, activeId) {
  const sel = document.getElementById('profile-select');
  if (!sel) return;

  sel.innerHTML = '';
  profiles.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name || 'PS5'} (${p.local_ip || 'Sin IP'})`;
    if (p.id === activeId) opt.selected = true;
    sel.appendChild(opt);
  });
}

function applyProfileToUI(p) {
  if (!p) return;
  activeProfile = p;

  // Actualizar IPs mostradas en el conmutador de red
  const localIpEl = document.getElementById('tab-mode-local-ip');
  const remoteIpEl = document.getElementById('tab-mode-remote-ip');
  if (localIpEl) localIpEl.textContent = p.local_ip || 'Sin configurar';
  if (remoteIpEl) remoteIpEl.textContent = p.remote_ip || 'Sin configurar';

  // Actualizar modo activo (local vs remote)
  const mode = p.connection_mode || 'local';
  updateNetworkModeTabs(mode);

  // Actualizar tira de estado
  updateConnectionStatusStrip(p, mode);

  // Sincronizar pestaña de vincular
  syncPairTab(p);

  // Actualizar etiqueta del botón de inicio según modelo de consola (PS5 o PS4)
  const isPs4 = (p.console_type === 'PS4' || (p.host_name && p.host_name.includes('PS4')));
  const launchTxt = document.querySelector('.btn-launch-stream .launch-text');
  if (launchTxt) {
    launchTxt.textContent = isPs4 ? "INICIAR PANTALLA REMOTA DE PS4" : "INICIAR PANTALLA REMOTA DE PS5";
  }

  // Sincronizar resolución, FPS y códec del perfil a la interfaz de usuario
  const resSelect = document.getElementById('set-resolution');
  if (resSelect && p.resolution) resSelect.value = p.resolution;
  const fpsSelect = document.getElementById('set-fps');
  if (fpsSelect && p.fps) fpsSelect.value = String(p.fps);
  const codecSelect = document.getElementById('set-codec');
  if (codecSelect && p.codec) codecSelect.value = p.codec;
  const hdrEl = document.getElementById('set-hdr');
  if (hdrEl && typeof p.hdr !== 'undefined') hdrEl.checked = !!p.hdr;
  const hudEl = document.getElementById('set-hud');
  if (hudEl && typeof p.show_hud !== 'undefined') hudEl.checked = !!p.show_hud;
  updateHdrAvailability();
}

function updateNetworkModeTabs(mode) {
  const localTab = document.getElementById('tab-mode-local');
  const remoteTab = document.getElementById('tab-mode-remote');

  if (mode === 'remote') {
    if (localTab) localTab.classList.remove('active');
    if (remoteTab) remoteTab.classList.add('active');
  } else {
    if (remoteTab) remoteTab.classList.remove('active');
    if (localTab) localTab.classList.add('active');
  }
}

function updateConnectionStatusStrip(p, mode) {
  const endpointEl = document.getElementById('cs-active-endpoint');
  const tagEl = document.getElementById('cs-pairing-status');
  const indEl = document.getElementById('cs-indicator');

  const isRemote = mode === 'remote';
  const targetIp = isRemote ? (p.remote_ip || 'IP Remota no configurada') : (p.local_ip || 'IP Local no configurada');
  const modeLabel = isRemote ? 'Internet / Remoto' : 'Red Local';

  if (endpointEl) {
    endpointEl.textContent = `${targetIp} (${modeLabel})`;
  }

  const isPaired = Boolean(p.rp_key);
  if (tagEl) {
    tagEl.textContent = isPaired ? 'Vinculada' : 'No vinculada';
    tagEl.className = 'cs-status-tag' + (isPaired ? '' : ' pending');
  }

  if (indEl) {
    indEl.style.backgroundColor = isPaired ? '#10B981' : '#F59E0B';
  }
}

function syncPairTab(p) {
  const pairNameEl = document.getElementById('pair-target-profile-name');
  const pairModeEl = document.getElementById('pair-target-profile-mode');
  const pairIpInput = document.getElementById('pair-ip');
  const pairAccInput = document.getElementById('pair-acc');
  const alreadyPairedCard = document.getElementById('pair-already-paired-card');
  const pairCard = document.querySelector('.pair-card');
  const quickRemoteIpInput = document.getElementById('quick-pair-remote-ip');
  const papLocalIpHint = document.getElementById('pap-local-ip-hint');

  if (pairNameEl) pairNameEl.textContent = p.name || 'PS5 Principal';
  if (pairModeEl) pairModeEl.textContent = `🏠 IP Local: ${p.local_ip || 'No configurada'}`;
  if (pairIpInput && p.local_ip) pairIpInput.value = p.local_ip;
  if (papLocalIpHint && p.local_ip) papLocalIpHint.textContent = p.local_ip;
  if (quickRemoteIpInput) quickRemoteIpInput.value = p.remote_ip || '';
  if (pairAccInput && p.account_id && p.account_id !== "AAAAAAAAAAAAAAAAAAAAAA==") {
    pairAccInput.value = p.account_id;
  }

  const cTypeSelect = document.getElementById('pair-console-type');
  if (cTypeSelect) {
    const cVal = p.console_type || (p.host_name && p.host_name.includes('PS4') ? 'PS4' : 'PS5');
    cTypeSelect.value = cVal;
    if (typeof onPairConsoleTypeChanged === 'function') {
      onPairConsoleTypeChanged(cVal);
    }
  }

  const isPaired = Boolean(p.rp_key);
  if (alreadyPairedCard) {
    alreadyPairedCard.style.display = isPaired ? 'block' : 'none';
  }
  if (pairCard) {
    pairCard.style.display = isPaired ? 'none' : 'block';
  }
}

// Guardar IP Pública directamente desde la pestaña de vinculación
async function saveQuickRemoteIp() {
  if (!activeProfile) return;
  const ipInput = document.getElementById('quick-pair-remote-ip');
  const rawVal = (ipInput ? ipInput.value : '').trim();
  // Limpiar posibles comas o IPv6 pegadas desde el portapapeles (ej: '201.85.x.x,fd7a:...')
  const val = rawVal.split(',')[0].trim().split(' ')[0].trim();
  if (ipInput) ipInput.value = val;
  if (!val) {
    await showPlayStationModal({
      title: "IP Pública Requerida",
      message: "Por favor introduce tu Dirección IP Pública o Hostname DDNS para configurar el Acceso Remoto.",
      icon: "🌐",
      showCancel: false
    });
    return;
  }

  try {
    const res = await window.pywebview.api.update_profile_remote_ip(activeProfile.id, val);
    if (res && res.success && res.profile) {
      applyProfileToUI(res.profile);
      await switchNetworkMode('remote');
      setMsg(`IP Pública '${val}' guardada. Modo cambiado a Acceso Remoto.`);
      await showPlayStationModal({
        title: "¡IP Remota Configurada!",
        message: `Se ha guardado <strong>${val}</strong> como IP Pública en el perfil <strong>${activeProfile.name}</strong>.<br><br>Se ha activado automáticamente el modo <strong>🌐 Acceso Remoto (Internet)</strong>.<br><br>¡Ya puedes iniciar la Pantalla Remota!`,
        icon: "🎮",
        confirmText: "Ir a Pantalla Remota",
        showCancel: false
      });
      switchTab('stream');
    } else {
      alert("Error al guardar IP: " + (res.error || ""));
    }
  } catch (err) {
    console.error("Error guardando IP remota:", err);
  }
}

function toggleRelinkForm() {
  const pairCard = document.querySelector('.pair-card');
  if (pairCard) {
    pairCard.style.display = (pairCard.style.display === 'none') ? 'block' : 'none';
    if (pairCard.style.display === 'block') {
      pairCard.scrollIntoView({ behavior: 'smooth' });
    }
  }
}

// Edición rápida de IP desde el selector de red
function quickEditIp(event, field) {
  if (event) event.stopPropagation();
  openProfileModal(false, field);
}

// Evento al cambiar perfil en el select
async function onProfileSelected(profileId) {
  try {
    const res = await window.pywebview.api.select_profile(profileId);
    if (res && res.success && res.profile) {
      applyProfileToUI(res.profile);
      setMsg(`Perfil activo: ${res.profile.name}`);
    }
  } catch (err) {
    console.error("Error al seleccionar perfil:", err);
  }
}

// Conmutar Modo de Red (Local vs Remoto)
async function switchNetworkMode(mode) {
  if (!activeProfile) return;

  if (mode === 'remote' && !activeProfile.remote_ip) {
    const wantConfig = await showPlayStationModal({
      title: "Configurar IP Pública",
      message: "Para jugar fuera de tu red local necesitas ingresar la <strong>IP Pública</strong> o <strong>Hostname DDNS</strong> de tu hogar.<br><br>¿Deseas ingresarla ahora?",
      icon: "🌐",
      confirmText: "Configurar IP",
      cancelText: "Cancelar",
      showCancel: true
    });
    if (wantConfig) {
      openProfileModal(false, 'remote');
    }
    return;
  }

  const wasAlreadySelected = activeProfile.connection_mode === mode;

  activeProfile.connection_mode = mode;
  updateNetworkModeTabs(mode);
  updateConnectionStatusStrip(activeProfile, mode);

  try {
    await window.pywebview.api.set_profile_mode(activeProfile.id, mode);
    const modeName = mode === 'remote' ? 'Acceso Remoto (Internet)' : 'Red Local (LAN)';
    setMsg(`Modo cambiado a: ${modeName}`);
  } catch (err) {
    console.error("Error al guardar modo:", err);
  }

  // Si se vuelve a pulsar el botón de Acceso Remoto estando activo, iniciar la pantalla remota directamente
  if (wasAlreadySelected) {
    await launchStream();
  }
}

// --------------------------------------------------------------------------
// 3. Modal de Configuración y Creación de Perfiles
// --------------------------------------------------------------------------
function openProfileModal(isNew = false, focusField = null) {
  if (typeof closeModal === 'function') closeModal(false);
  const modal = document.getElementById('profile-modal');
  const title = document.getElementById('prof-modal-title');
  const idInput = document.getElementById('prof-modal-id');
  const nameInput = document.getElementById('prof-modal-name');
  const localIpInput = document.getElementById('prof-modal-local-ip');
  const remoteIpInput = document.getElementById('prof-modal-remote-ip');
  const accInput = document.getElementById('prof-modal-acc');
  const pinInput = document.getElementById('prof-modal-pin');
  const pinGroup = document.getElementById('prof-modal-pin-group');
  const btnDelete = document.getElementById('btn-delete-profile');

  if (isNew) {
    title.textContent = "Nuevo Perfil de PS5 / PS4";
    idInput.value = "";
    nameInput.value = `PS5 #${allProfiles.length + 1}`;
    localIpInput.value = "192.168.1.";
    remoteIpInput.value = "";
    accInput.value = "";
    if (pinInput) pinInput.value = "";
    if (pinGroup) pinGroup.style.display = "block";
    if (btnDelete) btnDelete.style.display = "none";
  } else {
    if (!activeProfile) return;
    title.textContent = `Configurar: ${activeProfile.name || 'Perfil'}`;
    idInput.value = activeProfile.id;
    nameInput.value = activeProfile.name || "Mi PS5";
    localIpInput.value = activeProfile.local_ip || "192.168.1.100";
    remoteIpInput.value = activeProfile.remote_ip || "";
    accInput.value = (activeProfile.account_id && activeProfile.account_id !== "AAAAAAAAAAAAAAAAAAAAAA==") ? activeProfile.account_id : "";
    if (pinInput) pinInput.value = "";
    if (pinGroup) pinGroup.style.display = activeProfile.rp_key ? "none" : "block";
    if (btnDelete) btnDelete.style.display = allProfiles.length > 1 ? "block" : "none";
  }

  modal.classList.add('active');
  modal.classList.add('open');

  setTimeout(() => {
    if (focusField === 'remote' && remoteIpInput) {
      remoteIpInput.focus();
      remoteIpInput.select();
    } else if (focusField === 'local' && localIpInput) {
      localIpInput.focus();
      localIpInput.select();
    } else if (isNew && pinInput) {
      // Dejar que comience por nombre o IP
      if (nameInput) nameInput.focus();
    }
  }, 120);
}

function closeProfileModal() {
  const modal = document.getElementById('profile-modal');
  if (modal) {
    modal.classList.remove('active');
    modal.classList.remove('open');
  }
}

async function saveProfileFromModal() {
  const id = document.getElementById('prof-modal-id').value.trim();
  const name = document.getElementById('prof-modal-name').value.trim();
  const raw_local_ip = document.getElementById('prof-modal-local-ip').value.trim();
  const raw_remote_ip = document.getElementById('prof-modal-remote-ip').value.trim();
  const local_ip = raw_local_ip.split(',')[0].trim().split(' ')[0].trim();
  const remote_ip = raw_remote_ip.split(',')[0].trim().split(' ')[0].trim();
  const account_id = document.getElementById('prof-modal-acc').value.trim();
  const modalPinInput = document.getElementById('prof-modal-pin');
  const enteredPin = modalPinInput ? modalPinInput.value.trim() : "";

  if (!name || !local_ip) {
    await showPlayStationModal({
      title: "Campos Requeridos",
      message: "Por favor proporciona al menos un <strong>Nombre de Perfil</strong> y la <strong>IP Local</strong> de la consola.",
      icon: "⚠️",
      showCancel: false
    });
    return;
  }

  const isNewProfile = !id;
  const profileData = {
    id: id || undefined,
    name: name,
    local_ip: local_ip,
    remote_ip: remote_ip,
    account_id: account_id || (isNewProfile ? "" : (activeProfile ? activeProfile.account_id : ""))
  };

  if (isNewProfile) {
    profileData.regist_key = "";
    profileData.rp_key = "";
    profileData.status = "Pendiente";
  }

  try {
    const res = await window.pywebview.api.save_profile(profileData);
    if (res && res.success) {
      closeProfileModal();
      
      // Recargar perfiles
      const pRes = await window.pywebview.api.get_profiles();
      if (pRes && pRes.success) {
        allProfiles = pRes.profiles || [];
        renderProfileSelect(allProfiles, res.profile.id);
        applyProfileToUI(res.profile);
      }
      setMsg(`Perfil '${name}' guardado.`);

      // Si es un perfil nuevo:
      if (isNewProfile) {
        // Si el usuario ya introdujo el PIN de 8 dígitos en el modal, vincular de inmediato:
        if (enteredPin && enteredPin.length === 8 && /^\d+$/.test(enteredPin)) {
          setMsg(`Vinculando consola con PIN ${enteredPin}...`);
          switchTab('pair');
          const pairRes = await window.pywebview.api.pair_console(local_ip, enteredPin, account_id, res.profile.id, 'PS5');
          if (pairRes && pairRes.success) {
            await showPlayStationModal({
              title: "¡Consola Vinculada con Éxito!",
              message: `El perfil <strong>${name}</strong> se ha emparejado correctamente con tu consola PS5/PS4.<br><br>¡Ya puedes iniciar tu pantalla remota!`,
              icon: "✅",
              confirmText: "Jugar Ahora",
              showCancel: false
            });
            // Recargar datos y volver a la pestaña de transmisión
            const refreshed = await window.pywebview.api.get_initial_data();
            if (refreshed && refreshed.profiles) {
              allProfiles = refreshed.profiles;
              renderProfileSelect(allProfiles, res.profile.id);
              applyProfileToUI(refreshed.active_profile || res.profile);
            }
            switchTab('stream');
            focusPlayButton();
            return;
          } else {
            await showPlayStationModal({
              title: "Fallo en Vinculación",
              message: `No se pudo vincular con el PIN ingresado: ${pairRes ? (pairRes.error || pairRes.message) : 'Error de respuesta'}.<br><br>Verifica que la pantalla de vincular en tu PS5 siga activa y vuelve a introducir el PIN.`,
              icon: "⚠️",
              confirmText: "Reintentar PIN",
              showCancel: false
            });
            const pInput = document.getElementById('pair-pin');
            if (pInput) { pInput.value = enteredPin; pInput.focus(); }
            return;
          }
        }

        // Si no introdujo PIN, solicitarlo explícitamente y llevarlo a la pestaña Vincular
        await showPlayStationModal({
          title: "Vincular Consola con PIN",
          message: `El perfil <strong>${name}</strong> se ha creado.<br><br>Cada consola PS5 o PS4 requiere su propio <strong>PIN de 8 dígitos</strong> generado en su pantalla (Ajustes &gt; Sistema &gt; Uso a distancia &gt; Vincular dispositivo).<br><br>Introdúcelo a continuación para completar la vinculación.`,
          icon: "🔗",
          confirmText: "Ingresar PIN",
          showCancel: false
        });
        switchTab('pair');
        const pinInputEl = document.getElementById('pair-pin');
        if (pinInputEl) {
          pinInputEl.value = '';
          pinInputEl.focus();
        }
      }
    } else {
      alert("Error al guardar perfil: " + (res.error || ""));
    }
  } catch (err) {
    alert("Error de guardado: " + err);
  }
}

async function deleteCurrentProfile() {
  if (!activeProfile || allProfiles.length <= 1) return;

  const confirmDel = confirm(`¿Estás seguro de que deseas eliminar el perfil '${activeProfile.name}'?`);
  if (!confirmDel) return;

  try {
    const res = await window.pywebview.api.delete_profile(activeProfile.id);
    if (res && res.success) {
      closeProfileModal();
      allProfiles = res.profiles || [];
      activeProfile = res.active_profile;
      renderProfileSelect(allProfiles, activeProfile ? activeProfile.id : "");
      applyProfileToUI(activeProfile);
      setMsg("Perfil eliminado.");
    }
  } catch (err) {
    alert("Error al eliminar perfil: " + err);
  }
}

// --------------------------------------------------------------------------
// 4. Acciones de Red (Scan, Wake)
// --------------------------------------------------------------------------
async function silentScan() {
  try {
    const res = await window.pywebview.api.discover_consoles(2);
    if (res && res.success && res.consoles.length > 0) {
      const c = res.consoles[0];
      if (activeProfile && (!activeProfile.local_ip || activeProfile.local_ip === "192.168.1.100")) {
        activeProfile.local_ip = c.host_ip;
        activeProfile.host_name = c.host_name;
        activeProfile.host_id = c.host_id;
        applyProfileToUI(activeProfile);
      }
      setMsg(`PS5 detectada en red: ${c.host_name} (${c.host_ip}) - ${c.status}`);
    }
  } catch (e) {
    // Silencioso
  }
}

async function scanNetwork() {
  setMsg("Buscando consolas PS5 en red local (UDP 987)...");
  const scanBtn = document.getElementById('btn-scan');
  if (scanBtn) scanBtn.style.opacity = '0.6';

  try {
    const res = await window.pywebview.api.discover_consoles(3);
    if (res && res.success && res.consoles.length > 0) {
      const c = res.consoles[0];
      if (activeProfile) {
        activeProfile.local_ip = c.host_ip;
        activeProfile.host_name = c.host_name;
        activeProfile.host_id = c.host_id;
        applyProfileToUI(activeProfile);
        window.pywebview.api.save_profile(activeProfile);
      }
      setMsg(`¡PS5 encontrada!: ${c.host_name} en ${c.host_ip} (${c.status})`);
      await showPlayStationModal({
        title: "PS5 Encontrada",
        message: `Se detectó la consola <strong>${c.host_name}</strong> en la dirección IP <strong>${c.host_ip}</strong> (${c.status}). Se ha actualizado en tu perfil actual.`,
        icon: "🎮",
        showCancel: false
      });
    } else {
      setMsg("No se detectó ninguna PS5 por broadcast. Ingresa la IP manualmente.");
      await showPlayStationModal({
        title: "Búsqueda finalizada",
        message: "No se detectaron consolas por broadcast UDP.<br><br>Verifica que tu PS5 esté encendida o en reposo con la opción 'Activar encendido desde red' habilitada.",
        icon: "🔍",
        showCancel: false
      });
    }
  } catch (err) {
    setMsg("Error en escaneo: " + err);
  } finally {
    if (scanBtn) scanBtn.style.opacity = '1';
  }
}

async function wakeConsole() {
  const targetIp = activeProfile ? activeProfile.local_ip : "192.168.1.100";
  setMsg(`⚡ Encendiendo PlayStation 5 en ${targetIp}... Conectando automáticamente...`);

  try {
    // Enviar paquete Wake-on-LAN
    await window.pywebview.api.wakeup_console(targetIp, activeProfile ? activeProfile.id : null);
  } catch (err) {
    console.debug("Wakeup call:", err);
  }

  // Intentar la conexión remota de inmediato
  await launchStream();
}

function onPairConsoleTypeChanged(type) {
  const badge = document.getElementById('pair-console-badge');
  const btn = document.getElementById('btn-do-pair');
  const step1 = document.getElementById('pair-step-1-text');
  const step3 = document.getElementById('pair-step-3-text');
  const ipLabel = document.getElementById('pair-ip-label');
  if (badge) badge.textContent = type;
  if (type === 'PS4') {
    if (btn) btn.innerHTML = '<span>🔗 Vincular PS4 Ahora</span><span class="save-arrow">❯</span>';
    if (step1) step1.innerHTML = 'En tu consola PS4, ve a: <strong>Ajustes &gt; Ajustes de conexión del Uso a distancia &gt; Agregar dispositivo</strong>.';
    if (step3) step3.innerHTML = 'Introdúcelo a continuación y presiona <strong>Vincular PS4</strong>. ¡Listo para siempre!';
    if (ipLabel) ipLabel.textContent = 'Dirección IP Local de la PS4';
  } else {
    if (btn) btn.innerHTML = '<span>🔗 Vincular PS5 Ahora</span><span class="save-arrow">❯</span>';
    if (step1) step1.innerHTML = 'En tu consola PS5, ve a: <strong>Ajustes &gt; Sistema &gt; Uso a distancia &gt; Vincular dispositivo</strong>.';
    if (step3) step3.innerHTML = 'Introdúcelo a continuación y presiona <strong>Vincular PS5</strong>. ¡Listo para siempre!';
    if (ipLabel) ipLabel.textContent = 'Dirección IP Local de la PS5';
  }
}

// --------------------------------------------------------------------------
// 5. Vincular Consola con PIN
// --------------------------------------------------------------------------
async function executePairing() {
  const ip = document.getElementById('pair-ip').value.trim();
  const pin = document.getElementById('pair-pin').value.trim();
  const acc = document.getElementById('pair-acc').value.trim() || "";
  const cTypeSelect = document.getElementById('pair-console-type');
  const consoleType = cTypeSelect ? cTypeSelect.value : 'PS5';
  const feedback = document.getElementById('pair-feedback');
  const btn = document.getElementById('btn-do-pair');

  if (!ip || !pin) {
    await showPlayStationModal({
      title: "Datos Incompletos",
      message: "Por favor introduce la IP Local de la consola y el código PIN de 8 dígitos.",
      icon: "⚠️",
      showCancel: false
    });
    return;
  }

  if (pin.length !== 8 || isNaN(pin)) {
    await showPlayStationModal({
      title: "Código PIN Inválido",
      message: "El PIN debe contener exactamente <strong>8 dígitos numéricos</strong> sin espacios ni guiones.",
      icon: "⚠️",
      showCancel: false
    });
    return;
  }

  btn.style.opacity = '0.6';
  feedback.textContent = `Emparejando con la ${consoleType}... Espera un momento.`;
  feedback.style.color = "#F59E0B";

  try {
    const profId = activeProfile ? activeProfile.id : null;
    const res = await window.pywebview.api.pair_console(ip, pin, acc, profId, consoleType);

    if (res && res.success) {
      feedback.textContent = "¡Vinculación completada con éxito! Ya puedes transmitir.";
      feedback.style.color = "#10B981";

      if (res.profile) {
        applyProfileToUI(res.profile);
      }

      setMsg("Consola vinculada con éxito. Redirigiendo a pantalla remota...");
      setTimeout(() => switchTab('stream'), 1200);
    } else {
      feedback.textContent = "Error: " + (res.error || "No se pudo vincular.");
      feedback.style.color = "#EF4444";
      await showPlayStationModal({
        title: "Error al Vincular",
        message: res.error || "La PS5 rechazó la solicitud de vinculación.",
        icon: "❌",
        showCancel: false
      });
    }
  } catch (err) {
    feedback.textContent = "Error: " + err;
    feedback.style.color = "#EF4444";
  } finally {
    btn.style.opacity = '1';
  }
}

// --------------------------------------------------------------------------
// 6. Lanzar Pantalla Remota
// --------------------------------------------------------------------------
async function launchStream() {
  if (!activeProfile) {
    await showPlayStationModal({
      title: "Perfil no seleccionado",
      message: "Por favor crea o selecciona un perfil antes de iniciar.",
      icon: "🎮",
      showCancel: false
    });
    return;
  }

  const isRemote = activeProfile.connection_mode === 'remote';
  const targetIp = isRemote ? activeProfile.remote_ip : activeProfile.local_ip;

  if (isRemote && !activeProfile.remote_ip) {
    await showPlayStationModal({
      title: "IP Remota No Configurada",
      message: "Has seleccionado <strong>Acceso Remoto</strong>, pero este perfil no tiene una IP Pública o Hostname DDNS configurado.<br><br>Haz clic en <strong>Configurar IPs</strong> para ingresarla.",
      icon: "🌐",
      showCancel: false
    });
    openProfileModal(false, 'remote');
    return;
  }

  if (!isRemote && !activeProfile.local_ip) {
    await showPlayStationModal({
      title: "IP Local No Configurada",
      message: "Por favor especifica la IP Local de tu PS5 en tu red doméstica.",
      icon: "🏠",
      showCancel: false
    });
    openProfileModal(false, 'local');
    return;
  }

  // Iniciar directamente la pantalla remota
  await executeLaunchStream();
}

async function executeLaunchStream() {
  const isRemote = activeProfile.connection_mode === 'remote';
  const targetIp = isRemote ? activeProfile.remote_ip : activeProfile.local_ip;

  setMsg(`Iniciando Pantalla Remota con ${targetIp} (${isRemote ? 'Remoto' : 'LAN'})...`);
  const streamBtn = document.getElementById('btn-launch-stream');
  if (streamBtn) streamBtn.style.transform = 'scale(0.98)';

  try {
    const settings = await getSettingsFromUI();
    const res = await window.pywebview.api.launch_stream(activeProfile.id, settings);

    if (res && !res.success) {
      if (res.error === "not_paired") {
        const goPair = await showPlayStationModal({
          title: "Consola No Vinculada",
          message: `El perfil <strong>${activeProfile.name}</strong> (${targetIp}) aún no tiene claves de vinculación registradas.<br><br>¿Deseas ir ahora a la pestaña de Vinculación para emparejarla con el PIN de 8 dígitos de tu pantalla?`,
          icon: "🔗",
          confirmText: "Ir a Vincular",
          cancelText: "Cancelar",
          showCancel: true
        });

        if (goPair) {
          switchTab('pair');
          document.getElementById('pair-ip').value = activeProfile.local_ip || "";
        }
      } else {
        await showPlayStationModal({
          title: "Aviso de Conexión",
          message: res.message || res.error,
          icon: "⚠️",
          showCancel: false
        });
      }
    } else {
      const isAndroid = typeof window.DRPS5Native !== 'undefined';
      const isWebOS = typeof window.webOS !== 'undefined' || (!window.DRPS5Native && (!window.pywebview || !window.pywebview.api || window.location.protocol === 'file:'));

      if (isAndroid) {
        setMsg(`Transmisión en marcha con ${targetIp} en pantalla completa.`);
      } else if (isWebOS && typeof openStreamFullscreen === 'function') {
        setMsg(`Pantalla Remota Ultra Low Latency iniciada con ${targetIp} (1080p 60 FPS).`);
        openStreamFullscreen(activeProfile, settings);
      } else {
        setMsg(`Transmisión en marcha con ${targetIp}.`);
      }
    }
  } catch (err) {
    await showPlayStationModal({
      title: "Error Inesperado",
      message: "Error al lanzar la transmisión: " + err,
      icon: "⚠️",
      showCancel: false
    });
  } finally {
    if (streamBtn) streamBtn.style.transform = 'none';
  }
}

// --------------------------------------------------------------------------
// 6b. Pantalla Remota Completa en webOS / TV
// --------------------------------------------------------------------------
window.isStreamFullscreenActive = false;
let streamHudHideTimer = null;

function openStreamFullscreen(profile, settings) {
  window.isStreamFullscreenActive = true;
  const overlay = document.getElementById('webos-stream-overlay');
  if (!overlay) return;

  overlay.style.display = 'flex';

  // Configurar textos del HUD
  const isRemote = (profile && profile.connection_mode === 'remote');
  const targetIp = profile ? (isRemote ? (profile.remote_ip || profile.local_ip) : (profile.local_ip || profile.remote_ip)) : '192.168.1.100';
  const targetName = document.getElementById('webos-hud-target-name');
  if (targetName) targetName.textContent = `${(profile && profile.name) || 'Mi PS5'} (${targetIp})`;

  const resVal = (settings && settings.resolution) || (profile && profile.resolution) || '1080p';
  const fpsVal = (settings && settings.fps) || (profile && profile.fps) || 60;
  const hudRes = document.getElementById('webos-hud-res');
  if (hudRes) hudRes.textContent = resVal;
  const hudFps = document.getElementById('webos-hud-fps');
  if (hudFps) hudFps.textContent = fpsVal;

  const splashSub = document.getElementById('webos-stream-splash-sub');
  if (splashSub) {
    splashSub.textContent = `Iniciando reproductor nativo Ultra Low Latency 1080p 60 FPS con ${(profile && profile.name) || 'PS5'} en ${targetIp} (${isRemote ? 'Acceso Remoto' : 'Red Local'})...`;
  }

  // Enfocar el botón de salida
  setTimeout(() => {
    const exitBtn = document.getElementById('btn-webos-stream-exit');
    if (exitBtn) exitBtn.focus();
  }, 200);

  resetStreamHudTimer();

  // El reproductor nativo de baja latencia toma el primer plano en la TV.
  // Cerrar el overlay tras 3 segundos para que si el usuario regresa de la transmisión el menú esté limpio y listo.
  setTimeout(() => {
    closeStreamFullscreen();
  }, 3000);
}

function closeStreamFullscreen() {
  window.isStreamFullscreenActive = false;
  if (streamHudHideTimer) clearTimeout(streamHudHideTimer);

  const overlay = document.getElementById('webos-stream-overlay');
  if (overlay) overlay.style.display = 'none';

  const launchBtn = document.getElementById('btn-launch-stream');
  if (launchBtn) {
    launchBtn.focus();
    launchBtn.style.transform = 'none';
  }

  setMsg('Pantalla Remota finalizada. De vuelta al menú principal.');
}

function resetStreamHudTimer() {
  const hud = document.getElementById('webos-stream-hud');
  const ctrlHint = document.getElementById('webos-stream-ctrl-hint');
  if (hud) hud.style.opacity = '1';
  if (ctrlHint) ctrlHint.style.opacity = '1';

  if (streamHudHideTimer) clearTimeout(streamHudHideTimer);
  streamHudHideTimer = setTimeout(() => {
    if (window.isStreamFullscreenActive) {
      if (hud) hud.style.opacity = '0';
      if (ctrlHint) ctrlHint.style.opacity = '0';
    }
  }, 4500);
}

// --------------------------------------------------------------------------
// 7. Ajustes
// --------------------------------------------------------------------------
function applyConfigToUI(cfg) {
  const resSelect = document.getElementById('set-resolution');
  if (resSelect && cfg.resolution) resSelect.value = cfg.resolution;

  const fpsSelect = document.getElementById('set-fps');
  if (fpsSelect && cfg.fps) fpsSelect.value = String(cfg.fps);

  const codecSelect = document.getElementById('set-codec');
  if (codecSelect && cfg.codec) codecSelect.value = cfg.codec;

  const audioToggle = document.getElementById('set-audio');
  if (audioToggle && typeof cfg.audio_enabled !== 'undefined') {
    audioToggle.checked = Boolean(cfg.audio_enabled);
  }

  const fsToggle = document.getElementById('set-fullscreen');
  if (fsToggle && typeof cfg.fullscreen !== 'undefined') {
    fsToggle.checked = Boolean(cfg.fullscreen);
  }

  const hdrToggle = document.getElementById('set-hdr');
  if (hdrToggle && typeof cfg.hdr !== 'undefined') {
    hdrToggle.checked = Boolean(cfg.hdr);
  }

  const hudToggle = document.getElementById('set-hud');
  if (hudToggle && typeof cfg.show_hud !== 'undefined') {
    hudToggle.checked = Boolean(cfg.show_hud);
  }

  updateHdrAvailability();
}

function updateHdrAvailability() {
  const resSelect = document.getElementById('set-resolution');
  const resBadge = document.getElementById('res-select-badge');
  if (resSelect && resBadge) {
    const badgeMap = {
      '2160p': '4K',
      '1440p': '2K',
      '1080p': 'FHD',
      '720p': 'HD',
      '540p': 'SD',
      '360p': 'SD'
    };
    resBadge.textContent = badgeMap[resSelect.value] || 'UHD';
  }
  const codecSelect = document.getElementById('set-codec');
  const hdrEl = document.getElementById('set-hdr');
  const hdrContainer = document.getElementById('hdr-toggle-item');
  if (codecSelect && hdrEl) {
    if (codecSelect.value === 'h264') {
      hdrEl.checked = false;
      hdrEl.disabled = true;
      if (hdrContainer) hdrContainer.style.opacity = '0.45';
    } else {
      hdrEl.disabled = false;
      if (hdrContainer) hdrContainer.style.opacity = '1.0';
    }
  }
}

async function getSettingsFromUI() {
  const hudEl = document.getElementById('set-hud');
  const hdrEl = document.getElementById('set-hdr');
  return {
    resolution: document.getElementById('set-resolution').value,
    fps: parseInt(document.getElementById('set-fps').value, 10),
    codec: document.getElementById('set-codec').value,
    hdr: hdrEl ? hdrEl.checked : false,
    audio_enabled: document.getElementById('set-audio').checked,
    fullscreen: document.getElementById('set-fullscreen').checked,
    show_hud: hudEl ? hudEl.checked : true
  };
}

async function autoSaveSettings() {
  try {
    updateHdrAvailability();
    const settings = await getSettingsFromUI();
    if (activeProfile) {
      Object.assign(activeProfile, settings);
    }
    if (currentConfig) {
      Object.assign(currentConfig, settings);
    }
    await window.pywebview.api.save_settings(settings);
    setMsg("Ajustes sincronizados.");
  } catch (e) {
    console.error(e);
  }
}

async function manualSaveSettings() {
  try {
    const settings = await getSettingsFromUI();
    if (activeProfile) {
      Object.assign(activeProfile, settings);
    }
    if (currentConfig) {
      Object.assign(currentConfig, settings);
    }
    await window.pywebview.api.save_settings(settings);
    setMsg("Configuraciones guardadas con éxito.");

    // Feedback visual elegante en el botón de guardar sin popups intrusivos
    const saveBtn = document.querySelector('.btn-save-settings');
    if (saveBtn) {
      const origHtml = saveBtn.innerHTML;
      saveBtn.innerHTML = '<span>✓ ¡Ajustes Guardados con Éxito!</span>';
      saveBtn.style.background = 'linear-gradient(135deg, #10B981, #059669)';
      setTimeout(() => {
        saveBtn.innerHTML = origHtml;
        saveBtn.style.background = '';
      }, 1500);
    }

    // Regresar automáticamente a la ventana principal de pantalla remota
    setTimeout(() => {
      switchTab('stream');
      const launchBtn = document.getElementById('btn-launch-stream');
      if (launchBtn) launchBtn.focus();
    }, 450);
  } catch (e) {
    setMsg("Error al guardar: " + e);
  }
}

function setMsg(msg) {
  const el = document.getElementById('footer-msg');
  if (el) el.textContent = msg;
}

// --------------------------------------------------------------------------
// 8. Sistema de Modales Estilo PlayStation
// --------------------------------------------------------------------------
let modalResolve = null;

function showPlayStationModal(options = {}) {
  if (typeof closeProfileModal === 'function') closeProfileModal();
  const modal = document.getElementById('custom-modal');
  const title = document.getElementById('modal-title');
  const body = document.getElementById('modal-message');
  const icon = document.getElementById('modal-icon');
  const btnConfirm = document.getElementById('modal-btn-confirm');
  const btnCancel = document.getElementById('modal-btn-cancel');

  if (title) title.textContent = options.title || "Aviso";
  if (body) body.innerHTML = options.message || "";
  if (icon) icon.textContent = options.icon || "🎮";

  const textEl = document.getElementById('modal-btn-confirm-text');
  if (textEl) {
    textEl.textContent = options.confirmText || "Aceptar";
  }
  if (btnCancel) {
    btnCancel.style.display = options.showCancel ? 'inline-block' : 'none';
  }

  modal.classList.add('active');
  modal.classList.add('open');

  return new Promise((resolve) => {
    modalResolve = resolve;
  });
}

function closeModal(result) {
  const modal = document.getElementById('custom-modal');
  if (modal) {
    modal.classList.remove('active');
    modal.classList.remove('open');
  }
  if (modalResolve) {
    modalResolve(result);
    modalResolve = null;
  }
}

function closeAllModals() {
  closeModal(false);
  if (typeof closeProfileModal === 'function') closeProfileModal();
  document.querySelectorAll('.modal-overlay').forEach(m => {
    m.classList.remove('active');
    m.classList.remove('open');
  });
}
window.closeAllModals = closeAllModals;

// --------------------------------------------------------------------------
// 8. Visualizador de Registros y Diagnóstico
// --------------------------------------------------------------------------
async function loadLogs(showToast = false) {
  const terminal = document.getElementById('logs-terminal');
  if (!terminal) return;

  try {
    const res = await window.pywebview.api.get_logs("launcher", 350);
    if (res && res.success) {
      const logs = res.logs || "No hay eventos registrados.";
      renderLogs(logs);

      if (res.diagnosis) {
        applyDiagnosis(res.diagnosis);
      }

      if (res.file_path) {
        const pathEl = document.getElementById('logs-file-path');
        if (pathEl) pathEl.innerText = res.file_path;
      }

      const autoScroll = document.getElementById('logs-autoscroll');
      if (autoScroll && autoScroll.checked) {
        terminal.scrollTop = terminal.scrollHeight;
      }

      if (showToast) {
        setMsg("Registros de sesión actualizados.");
      }
    }
  } catch (err) {
    console.error("Error al cargar logs:", err);
  }
}

function renderLogs(rawText) {
  const terminal = document.getElementById('logs-terminal');
  if (!terminal) return;

  const lines = rawText.split('\n');
  const formattedHtml = lines.map(line => {
    let esc = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (line.includes('[ERROR]') || line.includes('Excepción') || line.includes('Traceback') || line.includes('KeyError')) {
      return `<div style="color: #F87171; background: rgba(239, 68, 68, 0.08); padding: 1px 4px; border-radius: 4px;">${esc}</div>`;
    } else if (line.includes('[WARNING]') || line.includes('warning') || line.includes('Corrupt Frame')) {
      return `<div style="color: #FBBF24;">${esc}</div>`;
    } else if (line.includes('🎮') || line.includes('Backbone') || line.includes('DualSense') || line.includes('conectado')) {
      return `<div style="color: #34D399; font-weight: 600;">${esc}</div>`;
    } else if (line.includes('Primer fotograma') || line.includes('autenticada y conectada') || line.includes('Session Started')) {
      return `<div style="color: #38BDF8; font-weight: 600;">${esc}</div>`;
    }
    return `<div>${esc}</div>`;
  }).join('');

  terminal.innerHTML = formattedHtml || '<div class="log-empty-msg">Sin eventos registrados</div>';
}

function applyDiagnosis(diag) {
  const banner = document.getElementById('log-diagnosis-banner');
  const icon = document.getElementById('diag-icon');
  const status = document.getElementById('diag-status');
  const detail = document.getElementById('diag-detail');
  if (!banner || !icon || !status || !detail) return;

  banner.className = 'log-diagnosis-banner';
  if (diag.status === 'error') {
    banner.classList.add('diag-error');
    icon.innerText = '🔴';
  } else if (diag.status === 'warning') {
    banner.classList.add('diag-warning');
    icon.innerText = '🟡';
  } else {
    icon.innerText = '🟢';
  }

  status.innerText = diag.title || 'Sistema Estable';
  detail.innerText = diag.detail || 'Registros normales.';
}

async function clearLogs() {
  try {
    await window.pywebview.api.clear_logs("stream");
    loadLogs(true);
    setMsg("Archivo de logs limpiado.");
  } catch (err) {
    console.error("Error al limpiar logs:", err);
  }
}

async function purgeOldLogs() {
  try {
    const res = await window.pywebview.api.purge_old_logs(30);
    await loadLogs(false);
    const msg = (res && res.message) ? res.message : "Registros con más de 30 días eliminados.";
    setMsg(msg);
    const detail = document.getElementById('diag-detail');
    if (detail) detail.innerText = msg;
  } catch (err) {
    console.error("Error al purgar logs antiguos:", err);
  }
}

async function openLogsFolder() {
  try {
    await window.pywebview.api.open_log_folder();
  } catch (err) {
    console.error("Error al abrir carpeta de logs:", err);
  }
}

// --------------------------------------------------------------------------
// 9. Calibración y Mapeo de Mandos (Backbone One / DualSense / etc.)
// --------------------------------------------------------------------------
let currentGamepadMapping = {
  ps_button: 14,
  touchpad_button: 16,
  options_button: 6,
  share_button: 4
};
let capturingAction = null;
let gamepadPollRaf = null;

// Temporizador de Prueba de Botones (40s) para Smart TV & Android
let gpTestTimerInterval = null;
let gpTestSecondsLeft = 0;
window._isGamepadTestingActive = false;

function toggleGamepadTestTimer(duration = 40) {
  if (window._isGamepadTestingActive) {
    stopGamepadTestTimer(true);
  } else {
    startGamepadTestTimer(duration);
  }
}

function startGamepadTestTimer(duration = 40) {
  window._isGamepadTestingActive = true;
  gpTestSecondsLeft = duration;

  const btn = document.getElementById('btn-gp-test-timer');
  const label = document.getElementById('btn-gp-test-timer-label');
  const badge = document.getElementById('gp-test-timer-badge');
  const secTxt = document.getElementById('gp-test-timer-seconds');

  if (btn) btn.classList.add('testing-active');
  if (badge) badge.style.display = 'inline-flex';
  if (secTxt) secTxt.textContent = `${gpTestSecondsLeft}s restantes`;
  if (label) label.textContent = `Pulsar para Finalizar Prueba (${gpTestSecondsLeft}s)`;

  // Notificar al puente nativo de Android para consumir eventos durante la prueba
  if (window.DRPS5Native && typeof window.DRPS5Native.setGamepadTabActive === 'function') {
    try { window.DRPS5Native.setGamepadTabActive(true); } catch(e) {}
  }

  setMsg(`⏱️ Prueba de Botones iniciada (40s): Comprueba tu mando libremente.`);

  if (gpTestTimerInterval) clearInterval(gpTestTimerInterval);
  gpTestTimerInterval = setInterval(() => {
    gpTestSecondsLeft--;
    if (secTxt) secTxt.textContent = `${gpTestSecondsLeft}s restantes`;
    if (label) label.textContent = `Pulsar para Finalizar Prueba (${gpTestSecondsLeft}s)`;

    if (gpTestSecondsLeft <= 0) {
      stopGamepadTestTimer(false);
    }
  }, 1000);
}

function stopGamepadTestTimer(userCancelled = false) {
  if (gpTestTimerInterval) {
    clearInterval(gpTestTimerInterval);
    gpTestTimerInterval = null;
  }
  window._isGamepadTestingActive = false;
  gpTestSecondsLeft = 0;

  const btn = document.getElementById('btn-gp-test-timer');
  const label = document.getElementById('btn-gp-test-timer-label');
  const badge = document.getElementById('gp-test-timer-badge');

  if (btn) btn.classList.remove('testing-active');
  if (badge) badge.style.display = 'none';
  if (label) label.textContent = 'Iniciar Prueba de Botones (40s)';

  // Desactivar bloqueo en Android para restaurar navegación
  if (window.DRPS5Native && typeof window.DRPS5Native.setGamepadTabActive === 'function') {
    try { window.DRPS5Native.setGamepadTabActive(false); } catch(e) {}
  }

  // Limpiar estados visuales de los botones
  for (let i = 0; i <= 20; i++) {
    const el = document.getElementById(`gp-btn-${i}`);
    if (el) el.classList.remove('pressed');
  }

  setMsg(userCancelled 
    ? 'Prueba de botones finalizada. Navegación con mando restaurada.' 
    : '⏱️ Tiempo de prueba finalizado. Navegación con mando restaurada.');
}

function setupGamepadButtonsGrid() {
  const grid = document.getElementById('gp-buttons-grid');
  if (!grid || grid.children.length > 0) return;

  const labels = [
    'B0 (Cruz / A)', 'B1 (Círculo / B)', 'B2 (Cuadrado / X)', 'B3 (Triángulo / Y)',
    'B4 (L1)', 'B5 (R1)', 'B6 (L2 Gatillo)', 'B7 (R2 Gatillo)',
    'B8 (Share / Captura)', 'B9 (Options / Start)', 'B10 (L3)', 'B11 (R3)',
    'B12 (D-Up)', 'B13 (D-Down)', 'B14 (D-Left)', 'B15 (D-Right)',
    'B16 (Botón PS)', 'B17 (Touchpad Clic)', 'B18 (Extra)', 'B19 (Extra)',
    'B20 (Touchpad DualSense)'
  ];

  for (let i = 0; i <= 20; i++) {
    const box = document.createElement('div');
    box.className = 'gp-btn-box';
    box.id = `gp-btn-${i}`;
    box.innerHTML = `
      <span class="gp-btn-number">${i}</span>
      <span class="gp-btn-name">${labels[i] || `B${i}`}</span>
    `;
    grid.appendChild(box);
  }
}

function updateMappingBadges() {
  const psBadge = document.getElementById('assigned-ps-badge');
  if (psBadge) {
    psBadge.innerText = `Botón ${currentGamepadMapping.ps_button ?? 14} (PS / Home)`;
  }
  const touchBadge = document.getElementById('assigned-touchpad-badge');
  if (touchBadge) {
    touchBadge.innerText = `Botón ${currentGamepadMapping.touchpad_button ?? 16} (Touchpad / Captura)`;
  }
  const optBadge = document.getElementById('assigned-options-badge');
  if (optBadge) {
    optBadge.innerText = `Botón ${currentGamepadMapping.options_button ?? 6} (Options)`;
  }
  const shareBadge = document.getElementById('assigned-share-badge');
  if (shareBadge) {
    shareBadge.innerText = `Botón ${currentGamepadMapping.share_button ?? 4} (Share / Create)`;
  }
}

function pollGamepadLoop() {
  const currentTab = document.querySelector('.tab-content.active');
  if (!currentTab || currentTab.id !== 'tab-gamepad') {
    if (gamepadPollRaf) clearTimeout(gamepadPollRaf);
    gamepadPollRaf = null;
    return;
  }

  let activeGp = null;

  // 1. Prioridad: Consulta de entradas de mando nativas en Android
  if (window.DRPS5Native && typeof window.DRPS5Native.getLiveGamepad === 'function') {
    try {
      const raw = window.DRPS5Native.getLiveGamepad();
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && parsed.connected) {
          activeGp = parsed;
        }
      }
    } catch (e) {}
  }

  // 2. Fallback: Web Gamepad API estándar (macOS / PC)
  if (!activeGp) {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (let i = 0; i < gamepads.length; i++) {
      if (gamepads[i] && gamepads[i].connected) {
        activeGp = gamepads[i];
        break;
      }
    }
  }

  const gpDot = document.getElementById('gp-dot');
  const gpDeviceName = document.getElementById('gp-device-name');

  if (activeGp) {
    if (gpDot) {
      gpDot.className = 'status-dot gp-dot-online';
    }
    if (gpDeviceName) {
      gpDeviceName.innerText = `🎮 ${activeGp.id} (${activeGp.buttons.length} botones, ${activeGp.axes.length} ejes)`;
    }

    // Actualizar visualizador de botones (B0 a B20)
    for (let i = 0; i <= 20; i++) {
      const btnEl = document.getElementById(`gp-btn-${i}`);
      if (!btnEl) continue;
      const btnObj = activeGp.buttons[i];
      const isPressed = btnObj ? (btnObj.pressed || btnObj.value > 0.5) : false;
      if (isPressed) {
        btnEl.classList.add('pressed');
        if (capturingAction) {
          handleCapturedButton(i);
        }
      } else {
        btnEl.classList.remove('pressed');
      }
    }

    // Actualizar Sticks
    if (activeGp.axes.length >= 2) {
      const lx = activeGp.axes[0] || 0;
      const ly = activeGp.axes[1] || 0;
      const lPoint = document.getElementById('gp-stick-left-point');
      const lCoords = document.getElementById('gp-stick-left-coords');
      if (lPoint) {
        lPoint.style.transform = `translate(calc(-50% + ${lx * 22}px), calc(-50% + ${ly * 22}px))`;
      }
      if (lCoords) {
        lCoords.innerText = `X: ${lx.toFixed(2)} | Y: ${ly.toFixed(2)}`;
      }
    }

    if (activeGp.axes.length >= 4) {
      const rx = activeGp.axes[2] || 0;
      const ry = activeGp.axes[3] || 0;
      const rPoint = document.getElementById('gp-stick-right-point');
      const rCoords = document.getElementById('gp-stick-right-coords');
      if (rPoint) {
        rPoint.style.transform = `translate(calc(-50% + ${rx * 22}px), calc(-50% + ${ry * 22}px))`;
      }
      if (rCoords) {
        rCoords.innerText = `X: ${rx.toFixed(2)} | Y: ${ry.toFixed(2)}`;
      }
    }

    // Gatillos L2 y R2
    const l2Btn = activeGp.buttons[6];
    const r2Btn = activeGp.buttons[7];
    const l2Val = l2Btn ? Math.round((l2Btn.value || (l2Btn.pressed ? 1 : 0)) * 100) : 0;
    const r2Val = r2Btn ? Math.round((r2Btn.value || (r2Btn.pressed ? 1 : 0)) * 100) : 0;

    const l2Fill = document.getElementById('gp-trigger-l2-fill');
    const l2Txt = document.getElementById('gp-trigger-l2-val');
    if (l2Fill) l2Fill.style.width = `${l2Val}%`;
    if (l2Txt) l2Txt.innerText = `${l2Val}%`;

    const r2Fill = document.getElementById('gp-trigger-r2-fill');
    const r2Txt = document.getElementById('gp-trigger-r2-val');
    if (r2Fill) r2Fill.style.width = `${r2Val}%`;
    if (r2Txt) r2Txt.innerText = `${r2Val}%`;

  } else {
    if (gpDot) {
      gpDot.className = 'status-dot gp-dot-offline';
    }
    if (gpDeviceName) {
      gpDeviceName.innerText = 'Ningún mando detectado (Pulsa cualquier botón de tu mando para activarlo)';
    }
    for (let i = 0; i <= 20; i++) {
      const btnEl = document.getElementById(`gp-btn-${i}`);
      if (btnEl) btnEl.classList.remove('pressed');
    }
  }

  gamepadPollRaf = setTimeout(pollGamepadLoop, 50);
}

function startCaptureButton(actionKey) {
  capturingAction = actionKey;
  if (window.DRPS5Native && typeof window.DRPS5Native.setCapturing === 'function') {
    window.DRPS5Native.setCapturing(true);
  }
  const btn = document.getElementById(`btn-capture-${actionKey}`);
  if (btn) {
    btn.classList.add('capturing');
    btn.innerHTML = '<span>⏳ Pulsa el botón en el mando...</span>';
  }
  setMsg(`Esperando pulsación en el mando para ${actionKey.toUpperCase()}...`);
}

function handleCapturedButton(btnIndex) {
  if (!capturingAction) return;
  const action = capturingAction;
  capturingAction = null;
  if (window.DRPS5Native && typeof window.DRPS5Native.setCapturing === 'function') {
    window.DRPS5Native.setCapturing(false);
  }

  if (action === 'ps') {
    currentGamepadMapping.ps_button = btnIndex;
  } else if (action === 'touchpad') {
    currentGamepadMapping.touchpad_button = btnIndex;
  } else if (action === 'options') {
    currentGamepadMapping.options_button = btnIndex;
  } else if (action === 'share') {
    currentGamepadMapping.share_button = btnIndex;
  }

  const btn = document.getElementById(`btn-capture-${action}`);
  if (btn) {
    btn.classList.remove('capturing');
    btn.innerHTML = '<span>🎯 Capturar Botón</span>';
  }

  updateMappingBadges();
  setMsg(`¡Asignado Botón ${btnIndex} para ${action.toUpperCase()}! Recuerda pulsar 'Guardar Mapeo'.`);
}

async function saveGamepadMappingToBackend() {
  try {
    const res = await window.pywebview.api.save_gamepad_mapping(currentGamepadMapping);
    if (res && res.success) {
      await showPlayStationModal({
        title: "Mapeo Guardado",
        message: "La configuración de botones para tu mando se ha guardado correctamente. Se aplicará automáticamente al iniciar la pantalla remota.",
        icon: "🎮",
        showCancel: false
      });
      // Redirigir a la pestaña de conexión (Pantalla Remota)
      switchTab('stream');
    } else {
      await showPlayStationModal({
        title: "Error al Guardar",
        message: "No se pudo guardar el mapeo: " + (res ? res.error : "Error desconocido"),
        icon: "⚠️",
        showCancel: false
      });
    }
  } catch (err) {
    await showPlayStationModal({
      title: "Error al Guardar",
      message: "Excepción al guardar mapeo: " + err,
      icon: "⚠️",
      showCancel: false
    });
  }
}

function resetGamepadMapping() {
  currentGamepadMapping = {
    ps_button: 5,
    touchpad_button: 20,
    options_button: 6,
    share_button: 4
  };
  updateMappingBadges();
  setMsg("Mapeo restaurado a valores por defecto (Backbone One / DualSense). Recuerda guardar.");
}

async function openSystemGameControllerSettings() {
  try {
    await window.pywebview.api.open_game_controller_settings();
  } catch (e) {
    console.error(e);
  }
}

async function pollConnectedControllers() {
  try {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.check_connected_controllers) {
      return;
    }
    const res = await window.pywebview.api.check_connected_controllers();
    const dot = document.getElementById('home-ctrl-dot');
    const nameEl = document.getElementById('home-ctrl-name');
    const statusEl = document.getElementById('home-ctrl-status');
    if (!dot || !nameEl || !statusEl) return;

    if (res && res.connected) {
      dot.className = 'cs-dot cs-dot-ctrl online pulse';
      nameEl.textContent = res.name || 'Mando Conectado';
      statusEl.textContent = 'Conectado';
      statusEl.className = 'cs-status-tag tag-online';

      const gpBadgeName = document.getElementById('gp-device-name');
      const gpDot = document.getElementById('gp-dot');
      if (gpBadgeName && gpDot && gpDot.classList.contains('gp-dot-offline')) {
        gpBadgeName.textContent = `${res.name} (Conectado • Pulsa cualquier botón para activar)`;
      }
    } else {
      dot.className = 'cs-dot cs-dot-ctrl offline';
      nameEl.textContent = 'Ningún mando detectado (Enciende tu mando)';
      statusEl.textContent = 'Desconectado';
      statusEl.className = 'cs-status-tag tag-offline';
    }
  } catch (err) {
    // ignorar
  }
}

// --------------------------------------------------------------------------
// 7. MOTOR DE NAVEGACIÓN DUAL: CURSOR VIRTUAL Y ESPACIAL (D-PAD / STICKS)
// --------------------------------------------------------------------------

// --- Estado del Cursor Virtual ---
window._cursorX = (typeof window !== 'undefined' && window.innerWidth > 0) ? (window.innerWidth / 2) : 960;
window._cursorY = (typeof window !== 'undefined' && window.innerHeight > 0) ? (window.innerHeight / 2) : 540;
window._cursorVisible = false;
window._hoveredElement = null;
let lastCursorMoveTime = 0;

function getVirtualCursorEl() {
  return document.getElementById('drps5-virtual-cursor');
}

function updateVirtualCursor(newX, newY) {
  const el = getVirtualCursorEl();
  if (!el) return;

  const maxX = window.innerWidth || 1920;
  const maxY = window.innerHeight || 1080;
  window._cursorX = Math.max(12, Math.min(maxX - 12, newX));
  window._cursorY = Math.max(12, Math.min(maxY - 12, newY));

  el.style.left = `${window._cursorX}px`;
  el.style.top = `${window._cursorY}px`;

  if (!window._cursorVisible) {
    el.classList.remove('hidden');
    window._cursorVisible = true;
  }

  // Detectar elemento interactivo bajo el cursor
  const rawTarget = document.elementFromPoint(window._cursorX, window._cursorY);
  const clickable = rawTarget ? rawTarget.closest('button, input, select, a, [onclick], .net-tab, .nav-pill, .btn-prof-pill, [tabindex="0"]') : null;

  if (clickable !== window._hoveredElement) {
    if (window._hoveredElement) {
      window._hoveredElement.classList.remove('gp-cursor-hover');
    }
    if (clickable) {
      clickable.classList.add('gp-cursor-hover');
      el.classList.add('hovering');
    } else {
      el.classList.remove('hovering');
    }
    window._hoveredElement = clickable;
  }
}

function hideVirtualCursor() {
  const el = getVirtualCursorEl();
  if (el) el.classList.add('hidden');
  if (window._hoveredElement) {
    window._hoveredElement.classList.remove('gp-cursor-hover');
    window._hoveredElement = null;
  }
  window._cursorVisible = false;
}

function triggerCursorClick() {
  const el = getVirtualCursorEl();
  if (el) {
    el.classList.add('clicking');
    setTimeout(() => el.classList.remove('clicking'), 150);
  }

  const rawTarget = document.elementFromPoint(window._cursorX, window._cursorY);
  const clickable = rawTarget ? rawTarget.closest('button, input, select, a, [onclick], .net-tab, .nav-pill, .btn-prof-pill, [tabindex="0"]') : null;

  if (clickable) {
    setElementFocus(clickable);
    try {
      clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: window._cursorX, clientY: window._cursorY }));
      clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: window._cursorX, clientY: window._cursorY }));
    } catch(e) {}
    if (typeof clickable.click === 'function') {
      clickable.click();
    }
  } else {
    // Si no apunta a nada concreto, intentar activar el botón principal
    const launchBtn = document.getElementById('btn-launch-stream');
    if (launchBtn && document.querySelector('.tab-content.active')?.id === 'tab-stream') {
      launchBtn.click();
    }
  }
}

// Sincronizar posición del cursor virtual con el ratón / Magic Remote / Touchpad hardware
window.addEventListener('mousemove', (e) => {
  window._cursorX = e.clientX;
  window._cursorY = e.clientY;
  const rawTarget = document.elementFromPoint(window._cursorX, window._cursorY);
  const clickable = rawTarget ? rawTarget.closest('button, input, select, a, [onclick], .net-tab, .nav-pill, .btn-prof-pill, [tabindex="0"]') : null;
  if (clickable !== window._hoveredElement) {
    if (window._hoveredElement) window._hoveredElement.classList.remove('gp-cursor-hover');
    if (clickable) clickable.classList.add('gp-cursor-hover');
    window._hoveredElement = clickable;
  }
}, { passive: true });

// --- Navegación Espacial con D-Pad (Modo Direccionales: Cruceta / Salto entre botones) ---
function setElementFocus(el) {
  if (!el) return;
  document.querySelectorAll('.gp-focused').forEach(e => e.classList.remove('gp-focused'));
  el.classList.add('gp-focused');
  el.focus();
  if (typeof el.scrollIntoView === 'function') {
    el.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
  }
}

window.dpadMoveFocus = function(dir) {
  // Al usar cruceta / teclado, ocultamos el cursor virtual para saltar limpiamente
  hideVirtualCursor();

  const activeModal = document.querySelector('.modal-overlay.active, .modal-overlay.open');
  const selector = 'button:not([disabled]):not([style*="display: none"]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), .net-tab, .nav-pill, .btn-prof-pill, [tabindex="0"]';

  let elements = [];
  if (activeModal) {
    elements = Array.from(activeModal.querySelectorAll(selector));
  } else {
    const sidebarEls = Array.from(document.querySelectorAll('.app-sidebar ' + selector));
    const contentEls = Array.from(document.querySelectorAll('.tab-content.active ' + selector));
    elements = sidebarEls.concat(contentEls);
  }

  // Filtrar únicamente elementos visibles
  elements = elements.filter(el => {
    if (el.offsetWidth <= 0 || el.offsetHeight <= 0) return false;
    const st = window.getComputedStyle(el);
    return st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
  });

  if (elements.length === 0) return;

  const currentTab = document.querySelector('.tab-content.active');
  const active = document.activeElement;

  if (!active || !elements.includes(active)) {
    const launchBtn = document.getElementById('btn-launch-stream');
    if (launchBtn && currentTab && currentTab.id === 'tab-stream' && elements.includes(launchBtn)) {
      setElementFocus(launchBtn);
    } else {
      setElementFocus(elements[0]);
    }
    return;
  }

  const curRect = active.getBoundingClientRect();
  const curCx = curRect.left + curRect.width / 2;
  const curCy = curRect.top + curRect.height / 2;

  let bestEl = null;
  let bestScore = Infinity;

  for (const el of elements) {
    if (el === active) continue;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const dx = cx - curCx;
    const dy = cy - curCy;

    let inDir = false;
    let mainDist = 0;
    let crossDist = 0;

    if (dir === 'up') {
      if (dy < -4) { inDir = true; mainDist = -dy; crossDist = Math.abs(dx); }
    } else if (dir === 'down') {
      if (dy > 4) { inDir = true; mainDist = dy; crossDist = Math.abs(dx); }
    } else if (dir === 'left') {
      if (dx < -4) { inDir = true; mainDist = -dx; crossDist = Math.abs(dy); }
    } else if (dir === 'right') {
      if (dx > 4) { inDir = true; mainDist = dx; crossDist = Math.abs(dy); }
    }

    if (inDir) {
      const score = mainDist * 1.0 + crossDist * 2.0;
      if (score < bestScore) {
        bestScore = score;
        bestEl = el;
      }
    }
  }

  if (bestEl) {
    setElementFocus(bestEl);
  }
};

// Navegación por teclado / Magic Remote / Flechas
window.addEventListener('keydown', (e) => {
  if (['ArrowUp', 'Up'].includes(e.key)) { window.dpadMoveFocus('up'); e.preventDefault(); }
  else if (['ArrowDown', 'Down'].includes(e.key)) { window.dpadMoveFocus('down'); e.preventDefault(); }
  else if (['ArrowLeft', 'Left'].includes(e.key)) { window.dpadMoveFocus('left'); e.preventDefault(); }
  else if (['ArrowRight', 'Right'].includes(e.key)) { window.dpadMoveFocus('right'); e.preventDefault(); }
  else if (e.key === 'Enter') {
    if (document.activeElement && typeof document.activeElement.click === 'function') {
      document.activeElement.click();
    }
  }
});

// Navegación Global con Mando / Gamepad por la interfaz
let lastGpNavTime = 0;
let lastGpButtonTime = 0;
const TABS_NAV_ORDER = ['stream', 'pair', 'settings', 'logs', 'gamepad', 'bluetooth'];

function navigateTabsRelative(delta) {
  const cur = document.querySelector('.tab-content.active');
  const curId = cur ? cur.id.replace('tab-', '') : 'stream';
  let idx = TABS_NAV_ORDER.indexOf(curId);
  if (idx === -1) idx = 0;
  idx = (idx + delta + TABS_NAV_ORDER.length) % TABS_NAV_ORDER.length;
  switchTab(TABS_NAV_ORDER[idx]);
}

function initGlobalGamepadNavigator() {
  function gamepadLoop(now) {
    try {
      // Si la prueba de botones (temporizador de 40s) está activa, pausar loop de navegación
      if (window._isGamepadTestingActive) {
        requestAnimationFrame(gamepadLoop);
        return;
      }

      const pads = (typeof navigator !== 'undefined' && typeof navigator.getGamepads === 'function') ? navigator.getGamepads() : [];
      let activePad = null;
      for (let i = 0; i < pads.length; i++) {
        if (pads[i] && pads[i].connected) {
          activePad = pads[i];
          break;
        }
      }

      if (activePad) {
        // Si la pantalla remota nativa o el overlay está activo
        if (window.isStreamFullscreenActive) {
          const b = activePad.buttons;
          const isExitCombo = (b[1] && b[1].pressed) || ((b[8] && b[8].pressed) && (b[9] && b[9].pressed));
          if (isExitCombo && (now - lastGpButtonTime > 300)) {
            lastGpButtonTime = now;
            closeStreamFullscreen();
          }
          requestAnimationFrame(gamepadLoop);
          return;
        }

        const b = activePad.buttons;
        const a = activePad.axes;

        // --- 1. MODO CURSOR: Stick Analógico Izquierdo o Derecho ---
        // (Ejes 0 y 1 = Stick izquierdo, Ejes 2 y 3 = Stick derecho)
        const lx = (a && a.length >= 2) ? a[0] : 0;
        const ly = (a && a.length >= 2) ? a[1] : 0;
        const rx = (a && a.length >= 4) ? a[2] : 0;
        const ry = (a && a.length >= 4) ? a[3] : 0;

        const stickX = Math.abs(lx) > 0.14 ? lx : (Math.abs(rx) > 0.18 ? rx : 0);
        const stickY = Math.abs(ly) > 0.14 ? ly : (Math.abs(ry) > 0.18 ? ry : 0);

        if (stickX !== 0 || stickY !== 0) {
          const speed = 19;
          const moveX = Math.sign(stickX) * Math.pow(Math.abs(stickX), 1.45) * speed;
          const moveY = Math.sign(stickY) * Math.pow(Math.abs(stickY), 1.45) * speed;
          updateVirtualCursor(window._cursorX + moveX, window._cursorY + moveY);
          lastCursorMoveTime = now;
        }

        // --- 2. MODO ESPACIAL: Cruceta (D-Pad) para saltar entre botones ---
        if (now - lastGpNavTime > 160) {
          let dir = null;
          if (b[12] && b[12].pressed) dir = 'up';
          else if (b[13] && b[13].pressed) dir = 'down';
          else if (b[14] && b[14].pressed) dir = 'left';
          else if (b[15] && b[15].pressed) dir = 'right';

          if (dir) {
            window.dpadMoveFocus(dir);
            lastGpNavTime = now;
          }
        }

        // --- 3. ACCIONES DE BOTONES Y CLICKS (Debounce 240ms) ---
        if (now - lastGpButtonTime > 240) {
          // L3 (Stick Izquierdo presionado - botón 10) o Click Touchpad (botón 17) -> Click en Cursor
          const isL3Click = (b[10] && b[10].pressed);
          const isTouchpadClick = (b[17] && b[17].pressed);

          if (isL3Click || isTouchpadClick) {
            lastGpButtonTime = now;
            triggerCursorClick();
          }
          // Botón 0: Cruz (Cross / A / Botón OK)
          else if (b[0] && b[0].pressed) {
            lastGpButtonTime = now;
            // Si el cursor virtual está visible y posicionado sobre un elemento, hacer click sobre él
            if (window._cursorVisible && window._hoveredElement) {
              triggerCursorClick();
            } else {
              // Modo espacial: click en el elemento enfocado por D-Pad
              const focused = document.activeElement;
              if (focused && typeof focused.click === 'function') {
                focused.click();
              } else {
                const launchBtn = document.getElementById('btn-launch-stream');
                if (launchBtn) launchBtn.click();
              }
            }
          }
          // Botón 1: Círculo (Circle / B) -> Atrás / Cancelar
          else if (b[1] && b[1].pressed) {
            lastGpButtonTime = now;
            const openModal = document.querySelector('.modal-overlay.active, .modal-overlay.open');
            if (openModal) {
              if (typeof closeAllModals === 'function') closeAllModals();
            } else {
              const activeTab = document.querySelector('.tab-content.active');
              if (activeTab && activeTab.id !== 'tab-stream') {
                switchTab('stream');
              }
            }
          }
          // Botón 4: L1 -> Pestaña anterior
          else if (b[4] && b[4].pressed) {
            lastGpButtonTime = now;
            navigateTabsRelative(-1);
          }
          // Botón 5: R1 -> Pestaña siguiente
          else if (b[5] && b[5].pressed) {
            lastGpButtonTime = now;
            navigateTabsRelative(1);
          }
        }
      }
    } catch(e) {}
    requestAnimationFrame(gamepadLoop);
  }
  requestAnimationFrame(gamepadLoop);
}

// Iniciar el navegador global de inmediato
initGlobalGamepadNavigator();

document.addEventListener('keydown', e => {
  if (
    e.key === 'F12' ||
    ((e.metaKey || e.ctrlKey) && e.altKey && ['i', 'j', 'u', 'c'].includes((e.key || '').toLowerCase())) ||
    ((e.metaKey || e.ctrlKey) && e.shiftKey && ['i', 'j', 'c'].includes((e.key || '').toLowerCase()))
  ) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  }
});

// ==========================================================================
// 8. GESTOR DE BLUETOOTH TV (webOS) & DETECCIÓN SILENCIOSA DE MANDOS
// ==========================================================================
let btScanning = false;
let btScanTimer = null;

function isGamepadConnectedLive() {
  if (typeof navigator !== 'undefined' && typeof navigator.getGamepads === 'function') {
    const pads = navigator.getGamepads();
    for (let i = 0; i < pads.length; i++) {
      if (pads[i] && pads[i].connected) return pads[i];
    }
  }
  return null;
}

function updateLiveGamepadStatusSilent() {
  const badge = document.getElementById('bt-connected-pad-badge');
  const liveText = document.getElementById('bt-live-pad-name');
  const gp = isGamepadConnectedLive();
  if (badge && liveText) {
    if (gp) {
      badge.classList.remove('disconnected');
      liveText.textContent = `🎮 ${gp.id.split('(')[0].trim() || 'Mando Activo'}`;
    } else if (window._btTvHidConnectedName) {
      badge.classList.remove('disconnected');
      liveText.textContent = `🎮 ${window._btTvHidConnectedName} (Pulsa un botón para activar)`;
    } else {
      badge.classList.add('disconnected');
      liveText.textContent = 'Sin mando activo en pantalla';
    }
  }

  // Sincronizar también con la tira de mando en la pestaña principal de transmisión
  const homeCtrlDot = document.getElementById('home-ctrl-dot');
  const homeCtrlName = document.getElementById('home-ctrl-name');
  const homeCtrlStatus = document.getElementById('home-ctrl-status');
  if (homeCtrlDot && homeCtrlName && homeCtrlStatus) {
    if (gp) {
      homeCtrlDot.className = 'cs-dot cs-dot-ctrl online';
      homeCtrlName.textContent = gp.id.split('(')[0].trim() || 'Mando Conectado';
      homeCtrlStatus.textContent = 'Activo';
      homeCtrlStatus.className = 'cs-status-tag tag-online';
    } else if (window._btTvHidConnectedName) {
      homeCtrlDot.className = 'cs-dot cs-dot-ctrl online';
      homeCtrlName.textContent = window._btTvHidConnectedName;
      homeCtrlStatus.textContent = 'Conectado al TV';
      homeCtrlStatus.className = 'cs-status-tag tag-online';
    }
  }
}

window.addEventListener('gamepadconnected', (e) => {
  updateLiveGamepadStatusSilent();
  setMsg(`Mando detectado: ${e.gamepad.id.split('(')[0].trim()}`);
});
window.addEventListener('gamepaddisconnected', () => {
  updateLiveGamepadStatusSilent();
});
setInterval(updateLiveGamepadStatusSilent, 1500);

function classifyBtDevice(name, rawType, cod, addr) {
  const n = (name || '').toLowerCase();
  const a = (addr || '').toLowerCase();
  if (n.includes('dualsense') || n.includes('wireless controller') || n.includes('playstation') || n.includes('xbox') || n.includes('gamepad') || n.includes('joy-con') || n.includes('pro controller') || n.includes('8bitdo') ||
      a.startsWith('10:18:49') || a.startsWith('00:1a:80') || a.startsWith('1c:a0:b8') || a.startsWith('20:9b:a6') || a.startsWith('70:20:84')) {
    return { type: 'gamepad', icon: '🎮', label: 'Mando de Juego' };
  }
  if (n.includes('headphone') || n.includes('headset') || n.includes('earbuds') || n.includes('airpods') || n.includes('speak') || n.includes('audio') || n.includes('sound') || n.includes('buds')) {
    return { type: 'audio', icon: '🎧', label: 'Audio / Auriculares' };
  }
  if (n.includes('keyboard') || n.includes('teclado')) {
    return { type: 'keyboard', icon: '⌨️', label: 'Teclado' };
  }
  if (n.includes('mouse') || n.includes('raton')) {
    return { type: 'mouse', icon: '🖱️', label: 'Ratón' };
  }
  return { type: 'other', icon: '📡', label: 'Dispositivo Bluetooth' };
}

async function loadBluetoothDevices() {
  const pairedList = document.getElementById('bt-paired-list');
  const discoveredList = document.getElementById('bt-discovered-list');
  const adapterText = document.getElementById('bt-adapter-text');
  const adapterDot = document.getElementById('bt-adapter-dot');

  updateLiveGamepadStatusSilent();

  try {
    const res = await window.pywebview.api.get_bluetooth_devices();
    if (!res || !res.success) {
      if (adapterText) adapterText.textContent = 'Bluetooth TV: No disponible o no soportado en esta plataforma';
      if (adapterDot) { adapterDot.className = 'status-dot gp-dot-offline'; }
      if (pairedList) pairedList.innerHTML = '<div class="bt-empty-state">El gestor de Bluetooth TV solo está activo en webOS. En esta plataforma el Bluetooth es gestionado por el sistema operativo.</div>';
      return;
    }

    if (adapterText) {
      const ad = res.adapter || {};
      adapterText.textContent = `Bluetooth TV: ${ad.powered ? 'Activo' : 'Inactivo'} (${ad.address || 'Adaptador'})`;
      if (adapterDot) adapterDot.className = 'status-dot ' + (ad.powered ? 'gp-dot-online' : 'gp-dot-offline');
    }

    // Renderizar Paired Devices (filtrando estrictamente entradas con MAC válida)
    const rawPaired = res.paired || [];
    const paired = rawPaired.filter(d => d && d.address && d.address.includes(':') && d.address.trim().length >= 11);

    // Detectar si algún mando o dispositivo HID está conectado al TV
    paired.forEach(d => {
      const isConn = (d.connectedProfiles && d.connectedProfiles.length > 0) || d.connected;
      const info = classifyBtDevice(d.name, d.typeOfDevice, d.classOfDevice, d.address);
      if (isConn && info.type === 'gamepad') {
        window._btTvHidConnectedName = d.name || 'DualSense Wireless Controller';
        window._btTvHidConnectedAddress = d.address;
      }
    });

    if (pairedList) {
      if (paired.length === 0) {
        pairedList.innerHTML = '<div class="bt-empty-state">No hay dispositivos emparejados aún. Pulsa "Buscar Mandos / Dispositivos" para vincular tu mando.</div>';
      } else {
        pairedList.innerHTML = paired.map(d => {
          const info = classifyBtDevice(d.name, d.typeOfDevice, d.classOfDevice, d.address);
          const isConn = (d.connectedProfiles && d.connectedProfiles.length > 0) || d.connected;
          return `
            <div class="bt-device-card" data-mac="${d.address}">
              <div class="bt-card-left">
                <div class="bt-device-type-icon">${info.icon}</div>
                <div class="bt-device-info-col">
                  <div class="bt-device-title-row">
                    <span class="bt-device-name">${d.name || 'Mando de Juego'}</span>
                    <span class="${isConn ? 'bt-tag-connected' : 'bt-tag-paired'}">${isConn ? 'Conectado' : 'Guardado en TV'}</span>
                  </div>
                  <span class="bt-device-mac">${d.address} • ${info.label}</span>
                </div>
              </div>
              <div class="bt-card-actions">
                ${!isConn ? `<button class="btn-bt-connect" onclick="connectBluetoothDevice('${d.address}', '${escapeHtml(d.name || '')}')"><span>⚡ Conectar</span></button>` : ''}
                <button class="btn-bt-unpair" onclick="unpairBluetoothDevice('${d.address}', '${escapeHtml(d.name || '')}')"><span>🗑️ Desvincular</span></button>
              </div>
            </div>
          `;
        }).join('');
      }
    }

    updateLiveGamepadStatusSilent();

    // Renderizar Discovered Devices (excluyendo los ya emparejados)
    const rawDiscovered = res.discovered || [];
    const discovered = rawDiscovered.filter(d => d && d.address && d.address.includes(':') && !paired.some(p => p.address === d.address));
    if (discoveredList && !btScanning) {
      if (discovered.length === 0) {
        discoveredList.innerHTML = '<div class="bt-empty-state">Pulsa "Buscar Mandos / Dispositivos" con tu mando o accesorio en modo de sincronización.</div>';
      } else {
        renderDiscoveredDevices(discovered);
      }
    }
  } catch(e) {
    if (adapterText) adapterText.textContent = 'Bluetooth TV: Error de comunicación con el servicio';
  }
}

function renderDiscoveredDevices(list) {
  const discoveredList = document.getElementById('bt-discovered-list');
  if (!discoveredList) return;
  const valid = list.filter(d => d && d.address && d.address.includes(':'));
  if (valid.length === 0) {
    discoveredList.innerHTML = '<div class="bt-empty-state">Buscando dispositivos cercanos... Pon tu mando en modo emparejamiento (Share + PS).</div>';
    return;
  }
  discoveredList.innerHTML = valid.map(d => {
    const info = classifyBtDevice(d.name, d.typeOfDevice, d.classOfDevice, d.address);
    return `
      <div class="bt-device-card" data-mac="${d.address}">
        <div class="bt-card-left">
          <div class="bt-device-type-icon">${info.icon}</div>
          <div class="bt-device-info-col">
            <div class="bt-device-title-row">
              <span class="bt-device-name">${d.name || 'Dispositivo Bluetooth'}</span>
            </div>
            <span class="bt-device-mac">${d.address} • ${info.label}</span>
          </div>
        </div>
        <div class="bt-card-actions">
          <button class="btn-bt-pair" onclick="pairBluetoothDevice('${d.address}', '${escapeHtml(d.name || '')}')">
            <span>🔗 Vincular al TV</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

async function startBluetoothScan() {
  const btnScan = document.getElementById('btn-bt-scan');
  const btnStop = document.getElementById('btn-bt-stop');
  const scanLabel = document.getElementById('btn-bt-scan-label');
  const discoveredList = document.getElementById('bt-discovered-list');

  btScanning = true;
  if (btnScan) btnScan.classList.add('scanning');
  if (scanLabel) scanLabel.textContent = 'Buscando mandos...';
  if (btnStop) btnStop.style.display = 'inline-flex';
  if (discoveredList) {
    discoveredList.innerHTML = '<div class="bt-empty-state"><div class="spinner" style="margin: 0 auto 10px;"></div>Buscando mandos y accesorios Bluetooth cercanos...</div>';
  }

  try {
    await window.pywebview.api.start_bluetooth_scan();
  } catch(e) {}

  clearInterval(btScanTimer);
  btScanTimer = setInterval(async () => {
    if (!btScanning) {
      clearInterval(btScanTimer);
      return;
    }
    try {
      const res = await window.pywebview.api.get_bluetooth_devices();
      if (res && res.success) {
        if (res.discovered) renderDiscoveredDevices(res.discovered);
      }
    } catch(e){}
  }, 2000);

  setTimeout(() => {
    if (btScanning) stopBluetoothScan();
  }, 30000);
}

async function stopBluetoothScan() {
  btScanning = false;
  clearInterval(btScanTimer);
  const btnScan = document.getElementById('btn-bt-scan');
  const btnStop = document.getElementById('btn-bt-stop');
  const scanLabel = document.getElementById('btn-bt-scan-label');

  if (btnScan) btnScan.classList.remove('scanning');
  if (scanLabel) scanLabel.textContent = 'Buscar Mandos / Dispositivos';
  if (btnStop) btnStop.style.display = 'none';

  try {
    await window.pywebview.api.stop_bluetooth_scan();
  } catch(e) {}
}

async function pairBluetoothDevice(address, name) {
  setMsg(`Vinculando '${name || address}' al televisor...`);
  await showPlayStationModal({
    title: "Vinculando Mando al TV",
    message: `Iniciando vinculación con <strong>${name || address}</strong>...<br><br>Mantén tu mando encendido. El televisor lo guardará para futuras sesiones sin volver a solicitar emparejamiento.`,
    icon: "📡",
    showCancel: false
  });

  try {
    const res = await window.pywebview.api.pair_bluetooth_device(address);
    if (res && res.success) {
      setMsg(`¡Dispositivo '${name || address}' vinculado al televisor!`);
      await showPlayStationModal({
        title: "¡Dispositivo Vinculado!",
        message: `<strong>${name || address}</strong> se ha vinculado exitosamente a tu Smart TV.<br><br>Ahora puedes usarlo directamente en tus juegos.`,
        icon: "✅",
        showCancel: false
      });
      stopBluetoothScan();
      await loadBluetoothDevices();
    } else {
      await showPlayStationModal({
        title: "Error de Vinculación",
        message: `No se pudo vincular con el dispositivo: ${res ? (res.error || res.message) : 'Tiempo de espera agotado'}.<br><br>Asegúrate de que el mando siga en modo de sincronización (luz parpadeando) y prueba de nuevo.`,
        icon: "⚠️",
        showCancel: false
      });
    }
  } catch(e) {
    setMsg("Error vinculando: " + e);
  }
}

async function unpairBluetoothDevice(address, name) {
  const confirmed = await showPlayStationModal({
    title: "Desvincular Dispositivo",
    message: `¿Estás seguro de desvincular <strong>${escapeHtml(name || address)}</strong> de tu televisor?`,
    icon: "🗑️",
    showCancel: true,
    confirmText: "Desvincular",
    cancelText: "Cancelar"
  });
  if (!confirmed) return;

  setMsg(`Desvinculando '${name || address}'...`);
  try {
    const res = await window.pywebview.api.unpair_bluetooth_device(address);
    if (res && res.success) {
      setMsg(`Dispositivo desvinculado.`);
      if (window._btTvHidConnectedAddress === address) {
        window._btTvHidConnectedName = null;
        window._btTvHidConnectedAddress = null;
      }
      await loadBluetoothDevices();
    } else {
      await showPlayStationModal({
        title: "Aviso",
        message: "No se pudo desvincular: " + (res.error || ""),
        icon: "⚠️",
        showCancel: false
      });
    }
  } catch(e) {
    setMsg("Error desvinculando: " + e);
  }
}

async function connectBluetoothDevice(address, name) {
  const displayName = name || 'DualSense Wireless Controller';
  setMsg(`Conectando '${displayName}'... Pulsa el botón PS en el mando.`);
  const card = document.querySelector(`[data-mac="${address}"] .btn-bt-connect`);
  if (card) {
    card.disabled = true;
    card.innerHTML = '<span>⏳ Conectando...</span>';
  }

  showPlayStationModal({
    title: "Conectar Mando con Smart TV",
    message: `Iniciando conexión Bluetooth con <strong>${escapeHtml(displayName)}</strong>.<br><br>👉 <b>IMPORTANTE:</b> Enciende tu mando pulsando el <b>botón PS</b> (o botón Xbox) para que active la antena inalámbrica y enlace con el televisor.`,
    icon: "⚡",
    showCancel: false,
    confirmText: "Entendido"
  });

  try {
    await window.pywebview.api.connect_bluetooth_device(address);
    let polls = 0;
    const pollInterval = setInterval(async () => {
      polls++;
      await loadBluetoothDevices();
      if (window._btTvHidConnectedAddress === address || polls >= 6) {
        clearInterval(pollInterval);
        if (card) {
          card.disabled = false;
          card.innerHTML = '<span>⚡ Conectar</span>';
        }
      }
    }, 2000);
  } catch(e) {
    setMsg("Error conectando: " + e);
    if (card) {
      card.disabled = false;
      card.innerHTML = '<span>⚡ Conectar</span>';
    }
  }
}

function escapeHtml(str) {
  return (str || '').replace(/[&<>'"]/g, tag => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[tag] || tag));
}
