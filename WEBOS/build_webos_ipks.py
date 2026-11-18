#!/usr/bin/env python3
"""
DRPS5 - webOS Package Builder
Genera las versiones Personal y Pública para LG Smart TV webOS (.ipk)
Resolución nativa: 1080p con reescalado automático por hardware para 4K/2K.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from PIL import Image

WORKSPACE_DIR = Path("/Users/rleon/Documents/PXPLAY")
WEBOS_DIR = WORKSPACE_DIR / "WEBOS"
GUI_DIR = WEBOS_DIR / "gui"
ARES_PACKAGE = Path("/Users/rleon/.nodejs/bin/ares-package")

PERSONAL_CONFIG = {
    "version": "1.3.1",
    "last_used_ip": "192.168.1.100",
    "resolution": "1080p",
    "fps": 60,
    "bitrate": "standard",
    "codec": "hevc",
    "audio_enabled": True,
    "fullscreen": True,
    "circle_confirm": False,
    "hdr": False,
    "show_hud": False,
    "consoles": {
        "": {
            "host_id": "",
            "host_name": "PS5",
            "host_ip": "192.168.1.100",
            "host_type": "PS5",
            "status": "Encendida"
        },
        "192.168.1.100": {
            "host_id": "",
            "host_name": "Mi PS5",
            "host_ip": "192.168.1.100",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada"
        }
    },
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "Mi PS5",
            "local_ip": "192.168.1.100",
            "remote_ip": "",
            "connection_mode": "local",
            "host_id": "",
            "host_name": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Vinculada",
            "resolution": "1080p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False,
            "audio_enabled": True,
            "fullscreen": True,
            "show_hud": False
        }
    },
    "gamepad_mapping": {
        "ps_button": 5,
        "touchpad_button": 20,
        "options_button": 6,
        "share_button": 4,
        "stick_deadzone": 0.12
    }
}

PUBLIC_CONFIG = {
    "version": "1.3.1",
    "last_used_ip": "",
    "resolution": "1080p",
    "fps": 60,
    "bitrate": "standard",
    "codec": "hevc",
    "audio_enabled": True,
    "fullscreen": True,
    "circle_confirm": False,
    "hdr": False,
    "show_hud": False,
    "consoles": {},
    "active_profile_id": "prof_ps5_main",
    "profiles": {
        "prof_ps5_main": {
            "id": "prof_ps5_main",
            "name": "PS5 Principal",
            "local_ip": "",
            "remote_ip": "",
            "connection_mode": "local",
            "host_id": "",
            "host_name": "PS5",
            "regist_key": "",
            "rp_key": "",
            "account_id": "",
            "status": "Pendiente",
            "resolution": "1080p",
            "fps": 60,
            "codec": "hevc",
            "hdr": False,
            "audio_enabled": True,
            "fullscreen": True,
            "show_hud": False
        }
    },
    "gamepad_mapping": {
        "ps_button": 5,
        "touchpad_button": 20,
        "options_button": 6,
        "share_button": 4,
        "stick_deadzone": 0.12
    }
}

SERVICE_JS = r"""'use strict';
process.argv.push('--disable-timeouts');
const http = require('http');
const dgram = require('dgram');
const fs = require('fs');
const path = require('path');
const os = require('os');
const crypto = require('crypto');
const cp = require('child_process');

let Service;
try {
  Service = require('webos-service');
} catch (e) {
  // Service mode standalone
}

const DATA_DIR = path.join(__dirname, 'data');
try { if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true }); } catch(e){}

// Mantener activo el event loop del servicio continuamente en webOS
setInterval(() => {}, 3600000);

const CONFIG_FILE = path.join(DATA_DIR, 'drps5_config.json');

// Cargar o sembrar configuración
let configData = {};
try {
  if (fs.existsSync(CONFIG_FILE)) {
    configData = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  }
} catch(e) {
  console.warn('Error leyendo config:', e.message);
}

// Si está vacía o es la edición personal sin claves, sembrar configuración
try {
  const seedPath = path.join(__dirname, 'seed_config.json');
  if (fs.existsSync(seedPath)) {
    const seedObj = JSON.parse(fs.readFileSync(seedPath, 'utf8'));
    const hasPersonalSeed = Boolean(seedObj && seedObj.profiles && seedObj.profiles.prof_ps5_main && seedObj.profiles.prof_ps5_main.regist_key);
    const isMissingKeys = Boolean(!configData.profiles || !configData.profiles.prof_ps5_main || !configData.profiles.prof_ps5_main.regist_key);
    if (!configData.profiles || Object.keys(configData.profiles).length === 0 || (hasPersonalSeed && isMissingKeys)) {
      configData = seedObj;
      fs.writeFileSync(CONFIG_FILE, JSON.stringify(configData, null, 2), 'utf8');
    }
  }
} catch(e) {
  console.warn('Error sembrando config:', e.message);
}

function saveConfig() {
  try {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(configData, null, 2), 'utf8');
  } catch(e) {
    console.error('Error guardando config:', e.message);
  }
}

function getActiveProfile() {
  const profs = configData.profiles || {};
  const activeId = configData.active_profile_id;
  if (activeId && profs[activeId]) return profs[activeId];
  const keys = Object.keys(profs);
  if (keys.length > 0) return profs[keys[0]];
  return null;
}

function getProfilesArray() {
  const profs = configData.profiles || {};
  return Object.keys(profs).map(k => profs[k]);
}

// Servidor REST en 127.0.0.1:8085 (Regla AC-05 / CLD.13.1.4: enlazado exclusivamente a loopback)
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }

  // Health check público (Regla CLD.9.5.2)
  if (req.url === '/health' || req.url === '/api/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'UP', service: 'drps5-webos', uptime: process.uptime() }));
    return;
  }

  const url = req.url;
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    let args = [];
    try {
      if (body) args = JSON.parse(body);
      if (!Array.isArray(args)) args = [args];
    } catch(e) {
      args = [];
    }

    handleApiRequest(url, args, (err, result) => {
      if (err) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ success: false, error: String(err) }));
      } else {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      }
    });
  });
});

function handleApiRequest(url, args, callback) {
  const route = url.replace('/api/', '').split('?')[0];

  switch(route) {
    case 'get_initial_data': {
      const activeP = getActiveProfile();
      callback(null, {
        config: configData,
        profiles: getProfilesArray(),
        active_profile: activeP,
        active_profile_id: activeP ? activeP.id : '',
        consoles: configData.consoles || {},
        last_used_ip: activeP ? (activeP.local_ip || '') : ''
      });
      break;
    }

    case 'get_profiles': {
      callback(null, {
        success: true,
        profiles: getProfilesArray(),
        active_profile_id: configData.active_profile_id || ''
      });
      break;
    }

    case 'select_profile': {
      const pid = args[0] || '';
      if (configData.profiles && configData.profiles[pid]) {
        configData.active_profile_id = pid;
        saveConfig();
        callback(null, { success: true, profile: configData.profiles[pid] });
      } else {
        callback(null, { success: false, error: 'Perfil no encontrado' });
      }
      break;
    }

    case 'set_profile_mode': {
      const pid = args[0] || '';
      const mode = args[1] || 'local';
      if (configData.profiles && configData.profiles[pid]) {
        configData.profiles[pid].connection_mode = mode;
        saveConfig();
        callback(null, { success: true });
      } else {
        callback(null, { success: false });
      }
      break;
    }

    case 'update_profile_remote_ip': {
      const pid = args[0] || '';
      const rip = String(args[1] || '').trim();
      if (configData.profiles && configData.profiles[pid]) {
        configData.profiles[pid].remote_ip = rip;
        saveConfig();
        callback(null, { success: true, profile: configData.profiles[pid] });
      } else {
        callback(null, { success: false });
      }
      break;
    }

    case 'save_profile': {
      const pData = args[0] || {};
      let pid = pData.id || '';
      const isNew = !pid;
      if (isNew) {
        pid = 'prof_' + Math.floor(Date.now() / 1000);
        pData.id = pid;
        pData.status = 'Pendiente';
        pData.regist_key = '';
        pData.rp_key = '';
      }
      if (!configData.profiles) configData.profiles = {};
      const existing = configData.profiles[pid] || {};
      Object.assign(existing, pData);
      configData.profiles[pid] = existing;
      configData.active_profile_id = pid;
      saveConfig();
      callback(null, { success: true, profile: existing, is_new: isNew });
      break;
    }

    case 'delete_profile': {
      const pid = args[0] || '';
      const profs = configData.profiles || {};
      if (Object.keys(profs).length > 1 && profs[pid]) {
        delete profs[pid];
        const nextActive = getActiveProfile();
        configData.active_profile_id = nextActive ? nextActive.id : '';
        saveConfig();
        callback(null, { success: true, profiles: getProfilesArray(), active_profile: nextActive });
      } else {
        callback(null, { success: false, error: 'Se requiere conservar al menos un perfil.' });
      }
      break;
    }

    case 'save_settings': {
      const st = args[0] || {};
      Object.assign(configData, st);
      const activeP = getActiveProfile();
      if (activeP) {
        ['resolution', 'fps', 'codec', 'hdr', 'audio_enabled', 'circle_confirm', 'fullscreen', 'show_hud'].forEach(k => {
          if (st[k] !== undefined) activeP[k] = st[k];
        });
      }
      saveConfig();
      callback(null, { success: true });
      break;
    }

    case 'discover_consoles': {
      discoverConsolesUdp(3000, (err, consoles) => {
        if (err) callback(null, { success: false, consoles: [] });
        else callback(null, { success: true, consoles });
      });
      break;
    }

    case 'wakeup_console': {
      const ip = args[0];
      const hostId = args[1] || '';
      const isPs4 = (args[2] === 'PS4');
      wakeupConsoleUdp(ip, hostId, isPs4, (err, ok) => {
        callback(null, { success: ok, error: err ? String(err) : undefined });
      });
      break;
    }

    case 'pair_console': {
      // Retorna instrucciones y estado para pairing
      callback(null, { success: true, message: 'Listo para registrar' });
      break;
    }

    case 'launch_stream': {
      const pid = args[0] || '';
      const p = configData.profiles && configData.profiles[pid] ? configData.profiles[pid] : getActiveProfile();
      if (!p) {
        callback(null, { success: false, error: 'missing_local_ip', message: 'No hay perfil seleccionado' });
        return;
      }
      if (!p.regist_key || !p.rp_key) {
        callback(null, {
          success: false,
          error: 'not_paired',
          message: 'El perfil no tiene claves de vinculación registradas. Introduce el PIN de 8 dígitos.'
        });
        return;
      }
      const mode = p.connection_mode || 'local';
      const targetIp = mode === 'remote' ? (p.remote_ip || p.local_ip) : (p.local_ip || p.remote_ip);
      const isPs5 = (p.host_type !== 'PS4');
      const mac = p.host_id || '5C:96:66:D6:53:E7';

      // Sincronizar credenciales y parámetros de Ultra Low Latency 1080p 60fps con Hotaru
      try {
        const confDir = '/tmp/hotaru';
        if (!fs.existsSync(confDir)) {
          fs.mkdirSync(confDir, { recursive: true, mode: 0o777 });
        }
        try { fs.chmodSync(confDir, 0o777); } catch(e) {}

        const confLines = [
          '# Hotaru Ultra Low Latency Settings (DRPS5)',
          'stream.codec=h265',
          'stream.width=1920',
          'stream.height=1080',
          'stream.fps=60',
          'stream.bitrate_kbps=15000',
          'stream.hdr=0',
          'stream.smooth_ms=0',
          'input.rumble=1',
          'input.touch=1',
          'host.0.nickname=' + (p.name || 'Mi PS5'),
          'host.0.addr=' + targetIp,
          'host.0.is_ps5=' + (isPs5 ? 1 : 0),
          'host.0.server_mac=' + mac,
          'host.0.rp_regist_key=' + p.regist_key,
          'host.0.rp_key=' + p.rp_key,
          'host.0.via_psn=0',
          'host.0.prefer_psn=0'
        ];
        const confPath = path.join(confDir, 'hotaru.conf');
        fs.writeFileSync(confPath, confLines.join('\n') + '\n', 'utf8');
        try { fs.chmodSync(confPath, 0o666); } catch(e) {}
        try {
          const logPath = '/tmp/hotaru.log';
          if (!fs.existsSync(logPath)) fs.writeFileSync(logPath, '', 'utf8');
          fs.chmodSync(logPath, 0o666);
        } catch(e) {}
      } catch (errConf) {
        console.warn('Error sincronizando conf de pantalla remota:', errConf.message);
      }

      // Lanzar el reproductor nativo de pantalla remota en webOS
      execLuna('luna://com.webos.applicationManager/launch', { id: 'com.renjfk.hotaru' }, (errLaunch, resLaunch) => {
        callback(null, {
          success: true,
          message: 'Transmisión Ultra Low Latency 1080p 60 FPS iniciada',
          target_ip: targetIp,
          resolution: '1080p',
          fps: 60,
          native_launch: resLaunch || { ok: true }
        });
      });
      break;
    }

    case 'get_gamepad_mapping': {
      callback(null, { success: true, mapping: configData.gamepad_mapping || {} });
      break;
    }

    case 'save_gamepad_mapping': {
      configData.gamepad_mapping = args[0] || {};
      saveConfig();
      callback(null, { success: true });
      break;
    }

    case 'get_logs': {
      callback(null, { success: true, logs: 'DRPS5 webOS Service Online (1080p / 4K Scaler Ready)\n' });
      break;
    }

    case 'clear_logs':
    case 'purge_old_logs':
    case 'open_log_folder': {
      callback(null, { success: true });
      break;
    }

    case 'get_bluetooth_devices': {
      getBluetoothStatus(callback);
      break;
    }

    case 'start_bluetooth_scan': {
      getBluetoothStatus((err, btData) => {
        const addr = (btData && btData.adapter && btData.adapter.adapterAddress) ? btData.adapter.adapterAddress : 'f4:20:15:c5:a1:af';
        execLuna('luna://com.webos.service.bluetooth2/adapter/startDiscovery', { adapterAddress: addr }, (errScan, resScan) => {
          callback(null, { success: true, result: resScan });
        });
      });
      break;
    }

    case 'stop_bluetooth_scan': {
      getBluetoothStatus((err, btData) => {
        const addr = (btData && btData.adapter && btData.adapter.adapterAddress) ? btData.adapter.adapterAddress : 'f4:20:15:c5:a1:af';
        execLuna('luna://com.webos.service.bluetooth2/adapter/cancelDiscovery', { adapterAddress: addr }, (errScan, resScan) => {
          callback(null, { success: true, result: resScan });
        });
      });
      break;
    }

    case 'pair_bluetooth_device': {
      const devAddr = String(args[0] || '').trim();
      const devName = String(args[1] || '').trim();
      if (!devAddr) {
        callback(null, { success: false, error: 'Dirección MAC requerida' });
        return;
      }
      const cmd = `luna-send-pub -n 1 -w 6000 luna://com.webos.service.bluetooth2/adapter/pair "{\\"address\\": \\"${devAddr}\\"}"`;
      cp.exec(cmd, { timeout: 8000 }, (pairErr, pairOut) => {
        if (!configData.bluetooth_devices) configData.bluetooth_devices = {};
        const lowerMac = devAddr.toLowerCase();
        let finalName = devName || 'Dispositivo Bluetooth';
        if (finalName === 'Dispositivo Bluetooth' && (lowerMac.startsWith('10:18:49') || lowerMac.startsWith('00:1a:80') || lowerMac.startsWith('1c:a0:b8') || lowerMac.startsWith('20:9b:a6') || lowerMac.startsWith('70:20:84'))) {
          finalName = 'DualSense Wireless Controller';
        }
        configData.bluetooth_devices[devAddr] = {
          address: devAddr,
          name: finalName,
          paired: true
        };
        saveConfig();
        execLuna('luna://com.webos.service.bluetooth2/hid/connect', { address: devAddr }, () => {});
        execLuna('luna://com.webos.service.bluetooth2/a2dp/connect', { address: devAddr }, () => {});
        callback(null, { success: true, message: 'Dispositivo emparejado en el televisor' });
      });
      break;
    }

    case 'unpair_bluetooth_device': {
      const devAddr = String(args[0] || '').trim();
      if (!devAddr) {
        callback(null, { success: false, error: 'Dirección MAC requerida' });
        return;
      }
      if (configData.bluetooth_devices && configData.bluetooth_devices[devAddr]) {
        delete configData.bluetooth_devices[devAddr];
        saveConfig();
      }
      execLuna('luna://com.webos.service.bluetooth2/adapter/unpair', { address: devAddr }, () => {});
      execLuna('luna://com.webos.service.bluetooth2/hid/disconnect', { address: devAddr }, () => {});
      callback(null, { success: true });
      break;
    }

    case 'connect_bluetooth_device': {
      const devAddr = String(args[0] || '').trim();
      if (!devAddr) {
        callback(null, { success: false, error: 'Dirección MAC requerida' });
        return;
      }
      execLuna('luna://com.webos.service.bluetooth2/hid/connect', { address: devAddr }, () => {});
      execLuna('luna://com.webos.service.bluetooth2/a2dp/connect', { address: devAddr }, () => {});
      callback(null, { success: true, message: 'Solicitud de conexión enviada' });
      break;
    }

    default:
      callback(null, { success: false, error: 'Unknown method: ' + route });
  }
}

// Helpers para Bluetooth en webOS
function execLuna(uri, params, cb) {
  const paramStr = JSON.stringify(params || {}).replace(/"/g, '\\"');
  const cmd = `luna-send-pub -n 1 ${uri} "${paramStr}"`;
  cp.exec(cmd, { timeout: 6000 }, (err, stdout) => {
    if (err) return cb ? cb(err) : null;
    try {
      const parsed = JSON.parse(stdout.trim());
      if (cb) cb(null, parsed);
    } catch(e) {
      if (cb) cb(e);
    }
  });
}

function getBluetoothStatus(cb) {
  execLuna('luna://com.webos.service.bluetooth2/adapter/getStatus', {}, (errAd, adRes) => {
    let adapterInfo = { powered: true, address: 'f4:20:15:c5:a1:af', discovering: false };
    if (adRes && adRes.adapters && adRes.adapters.length > 0) {
      adapterInfo = adRes.adapters[0];
    }
    execLuna('luna://com.webos.service.bluetooth2/device/getStatus', {}, (errDev, devRes) => {
      const rawDevices = (devRes && devRes.devices) ? devRes.devices : [];
      const paired = [];
      const discovered = [];
      const savedList = configData.bluetooth_devices || {};

      rawDevices.forEach(d => {
        if (!d || !d.address || !d.address.includes(':') || d.address.length < 11) return;
        const saved = savedList[d.address];
        const isPaired = Boolean(d.paired || d.trusted || saved);
        if ((!d.name || d.name.trim() === '') && saved && saved.name) {
          d.name = saved.name;
        }
        const lowerMac = d.address.toLowerCase();
        if (!d.name || d.name.trim() === '' || d.name === 'Dispositivo Bluetooth') {
          if (lowerMac.startsWith('10:18:49') || lowerMac.startsWith('00:1a:80') || lowerMac.startsWith('1c:a0:b8') || lowerMac.startsWith('20:9b:a6') || lowerMac.startsWith('70:20:84')) {
            d.name = 'DualSense Wireless Controller';
            d.typeOfDevice = 'gamepad';
          }
        }
        if (isPaired) {
          paired.push(d);
        } else {
          discovered.push(d);
        }
      });

      Object.keys(savedList).forEach(addr => {
        if (addr && addr.includes(':') && addr.length >= 11 && !paired.some(p => p.address === addr)) {
          const item = Object.assign({}, savedList[addr]);
          const lowerMac = addr.toLowerCase();
          if (!item.name || item.name === 'Dispositivo Bluetooth') {
            if (lowerMac.startsWith('10:18:49') || lowerMac.startsWith('00:1a:80') || lowerMac.startsWith('1c:a0:b8') || lowerMac.startsWith('20:9b:a6') || lowerMac.startsWith('70:20:84')) {
              item.name = 'DualSense Wireless Controller';
              item.typeOfDevice = 'gamepad';
            }
          }
          paired.push(item);
        }
      });

      cb(null, {
        success: true,
        adapter: adapterInfo,
        paired: paired,
        discovered: discovered
      });
    });
  });
}

// Descubrimiento DDP por broadcast UDP 987
function discoverConsolesUdp(timeoutMs, cb) {
  const socket = dgram.createSocket('udp4');
  const found = [];
  const searchMsg = Buffer.from('SRCH * HTTP/1.1\r\ndevice-discovery-protocol-version:0003001\r\n\r\n', 'utf8');

  socket.on('message', (msg, rinfo) => {
    try {
      const text = msg.toString('utf8');
      if (text.includes('HTTP/1.1 200 OK') || text.includes('host-id:')) {
        const lines = text.split('\r\n');
        const c = { host_ip: rinfo.address, status: 'Encendida' };
        lines.forEach(l => {
          const idx = l.indexOf(':');
          if (idx > 0) {
            const k = l.substring(0, idx).trim().toLowerCase();
            const v = l.substring(idx + 1).trim();
            if (k === 'host-id') c.host_id = v;
            else if (k === 'host-name') c.host_name = v;
            else if (k === 'host-type') c.host_type = v;
            else if (k === 'status-code') c.status = (v === '200') ? 'Encendida' : 'En Reposo';
          }
        });
        if (c.host_name && !found.some(x => x.host_ip === c.host_ip)) {
          found.push(c);
        }
      }
    } catch(e) {}
  });

  socket.bind(0, () => {
    try {
      socket.setBroadcast(true);
      socket.send(searchMsg, 0, searchMsg.length, 987, '255.255.255.255');
      socket.send(searchMsg, 0, searchMsg.length, 987, '192.168.1.255');
    } catch(e){}
  });

  setTimeout(() => {
    try { socket.close(); } catch(e){}
    cb(null, found);
  }, timeoutMs);
}

// Encendido de consola vía UDP 987
function wakeupConsoleUdp(ip, hostId, isPs4, cb) {
  const socket = dgram.createSocket('udp4');
  const targetHost = (hostId && hostId.length >= 8) ? hostId : '000000000000';
  const targetIp = (ip && ip.includes('.')) ? ip : '255.255.255.255';
  const payload = 'WAKEUP * HTTP/1.1\r\n'
    + 'host-id:' + targetHost + '\r\n'
    + 'device-discovery-protocol-version:' + (isPs4 ? '0002001' : '0003001') + '\r\n\r\n';
  const buf = Buffer.from(payload, 'utf8');

  socket.bind(0, () => {
    try {
      socket.setBroadcast(true);
      socket.send(buf, 0, buf.length, 987, targetIp, (err) => {
        try { socket.close(); } catch(e){}
        if (cb) cb(err, !err);
      });
    } catch(e) {
      try { socket.close(); } catch(err2){}
      if (cb) cb(e, false);
    }
  });
}

const PORT = 8085;
const HOST = '127.0.0.1';
server.listen(PORT, HOST, () => {
  console.log(`[DRPS5 webOS] Service listening on http://${HOST}:${PORT}`);
});

// Luna Bus Service (si está en webOS)
if (Service) {
  const s = new Service('com.drps5.remoteplay.service', null, { idleTimer: 999999, noBuiltinMethods: true });
  if (s.activityManager) {
    s.activityManager.exitOnTimeout = false;
    s.activityManager._stopTimer();
  }
  s.register('status', (message) => {
    message.respond({ returnValue: true, status: 'running', port: PORT });
  });
}
"""


def build_edition(is_personal: bool):
    suffix = "Personal" if is_personal else "Publico"
    out_ipk_name = f"com.drps5.remoteplay_1.3.1_{suffix.lower()}_all.ipk"
    stage_dir = WEBOS_DIR / f"_stage_{suffix.lower()}"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    app_dir = stage_dir / "app"
    svc_dir = stage_dir / "service"
    app_dir.mkdir(parents=True, exist_ok=True)
    svc_dir.mkdir(parents=True, exist_ok=True)

    # 1. appinfo.json (1080p nativo con reescalado 4K por hardware K8LP)
    app_info = {
        "id": "com.drps5.remoteplay",
        "version": "1.3.1",
        "vendor": "DRPS5",
        "type": "web",
        "main": "index.html",
        "title": "DRPS5 Remote Play" + (" (Personal)" if is_personal else ""),
        "icon": "icon.png",
        "largeIcon": "largeIcon.png",
        "resolution": "1920x1080",
        "transparent": False,
        "requiredMemory": 64,
        "requiredACG": [],
        "handlesRelaunch": True
    }
    (app_dir / "appinfo.json").write_text(json.dumps(app_info, indent=2), encoding="utf-8")

    # 3. Copiar assets del GUI
    shutil.copytree(GUI_DIR, app_dir, dirs_exist_ok=True)

    # Inyectar semilla de configuración inicial en el HTML para renderizado instantáneo
    seed = PERSONAL_CONFIG if is_personal else PUBLIC_CONFIG
    html_file = app_dir / "index.html"
    if html_file.exists():
        html_txt = html_file.read_text(encoding="utf-8")
        initial_data = {
            "config": seed,
            "profiles": list(seed.get("profiles", {}).values()),
            "active_profile": seed.get("profiles", {}).get(seed.get("active_profile_id")),
            "active_profile_id": seed.get("active_profile_id"),
            "consoles": seed.get("consoles", {}),
            "last_used_ip": seed.get("last_used_ip", "")
        }
        injected = f'<script>window.__INITIAL_DATA__ = {json.dumps(initial_data)};</script>'
        html_txt = html_txt.replace('<!-- INJECT_SEED_DATA -->', injected)
        html_file.write_text(html_txt, encoding="utf-8")

    # Generar iconos requeridos por webOS (80x80 y 130x130)
    icon_src = WORKSPACE_DIR / "DRPS5" / "app_icon_1024.png"
    img = Image.open(icon_src).convert("RGBA")
    img.resize((80, 80), Image.Resampling.LANCZOS).save(app_dir / "icon.png", format="PNG")
    img.resize((130, 130), Image.Resampling.LANCZOS).save(app_dir / "largeIcon.png", format="PNG")

    # 4. Service backend
    svc_info = {
        "id": "com.drps5.remoteplay.service",
        "description": "DRPS5 Remote Play Backend Service",
        "services": [
            { "name": "com.drps5.remoteplay.service" }
        ]
    }
    (svc_dir / "services.json").write_text(json.dumps(svc_info, indent=2), encoding="utf-8")

    svc_pkg = {
        "name": "com.drps5.remoteplay.service",
        "version": "1.3.1",
        "main": "service.js"
    }
    (svc_dir / "package.json").write_text(json.dumps(svc_pkg, indent=2), encoding="utf-8")

    (svc_dir / "service.js").write_text(SERVICE_JS, encoding="utf-8")

    # Semilla de configuración
    seed = PERSONAL_CONFIG if is_personal else PUBLIC_CONFIG
    (svc_dir / "seed_config.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    # 5. Empaquetar con ares-package
    cmd = [
        str(ARES_PACKAGE),
        "-o", str(WEBOS_DIR),
        str(app_dir),
        str(svc_dir)
    ]
    print(f"[*] Empaquetando webOS IPK ({suffix})...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[!] Error ares-package:\n{res.stderr}")
        sys.exit(res.returncode)

    # El ares-package genera com.drps5.remoteplay_1.3.1_all.ipk
    default_ipk = WEBOS_DIR / "com.drps5.remoteplay_1.3.1_all.ipk"
    target_ipk = WEBOS_DIR / out_ipk_name
    if default_ipk.exists():
        if target_ipk.exists():
            target_ipk.unlink()
        default_ipk.rename(target_ipk)

    print(f"[+] Generado con éxito: {target_ipk} ({target_ipk.stat().st_size} bytes)")
    return target_ipk


def main():
    print("=================================================================")
    print("  DRPS5 - Compilación de Paquetes webOS para LG Smart TV         ")
    print("=================================================================")
    ipk_personal = build_edition(is_personal=True)
    ipk_publico = build_edition(is_personal=False)

    # Copia canónica para instalación directa
    shutil.copy2(ipk_personal, WEBOS_DIR / "com.drps5.remoteplay_1.3.1_all.ipk")

    print("\n[OK] Ambos paquetes webOS generados correctamente en /Users/rleon/Documents/PXPLAY/WEBOS:")
    print(f"  - Personal: {ipk_personal.name}")
    print(f"  - Público:  {ipk_publico.name}")


if __name__ == "__main__":
    main()
