/**
 * KD Dashboard Module
 * Main interface with Three.js globe, telemetry, and command dock
 */

import * as THREE from 'three';
import { installGestures } from './gestures.js';
import { escapeHtml, commandBody, websocketUrl, telemetryMetrics } from './protocol.js';

// Configuration
const CONFIG = {
  apiBase: '/api',
  wsBase: '/ws',
  telemetryInterval: 2000,
  clockInterval: 1000,
};

// State
const state = {
  scene: null,
  camera: null,
  renderer: null,
  globe: null,
  particles: null,
  animationId: null,
  ws: null,
  telemetryTimer: null,
  clockTimer: null,
  currentMode: 'command',
  detailPanelOpen: false,
  selectedObject: null,
  user: null,
  telemetry: {},
};

// DOM elements cache
const els = {};

// Initialize DOM references
function cacheElements() {
  // HUD elements
  els.clockTime = document.getElementById('clockTime');
  els.clockDate = document.getElementById('clockDate');
  els.cpuVal = document.getElementById('cpuVal');
  els.gpuVal = document.getElementById('gpuVal');
  els.vramVal = document.getElementById('vramVal');
  els.ramVal = document.getElementById('ramVal');
  els.modelVal = document.getElementById('modelVal');
  els.latencyVal = document.getElementById('latencyVal');
  els.sysUptime = document.getElementById('sysUptime');
  els.sysProcs = document.getElementById('sysProcs');
  els.sysOs = document.getElementById('sysOs');
  els.sysKernel = document.getElementById('sysKernel');
  els.infModel = document.getElementById('infModel');
  els.infTps = document.getElementById('infTps');
  els.infCtx = document.getElementById('infCtx');
  els.infQueue = document.getElementById('infQueue');
  els.featureList = document.getElementById('featureList');
  els.agentList = document.getElementById('agentList');

  // Dock
  els.micBtn = document.getElementById('micBtn');
  els.stopBtn = document.getElementById('stopBtn');
  els.cmdInput = document.getElementById('cmdInput');
  els.sendBtn = document.getElementById('sendBtn');
  els.screenBtn = document.getElementById('screenBtn');
  els.cameraBtn = document.getElementById('cameraBtn');
  els.termBtn = document.getElementById('termBtn');
  els.videoBtn = document.getElementById('videoBtn');
  els.eStopBtn = document.getElementById('eStopBtn');

  // Navigation
  els.modeBtns = document.querySelectorAll('[data-mode]');
  els.detailPanel = document.getElementById('detailPanel');
  els.detailTitle = document.getElementById('detailTitle');
  els.detailContent = document.getElementById('detailContent');
  els.closeBtn = document.getElementById('closeBtn');
  els.detailAction1 = document.getElementById('detailAction1');
  els.detailAction2 = document.getElementById('detailAction2');

  // Tooltip
  els.tooltip = document.getElementById('tooltip');
}

// Utility functions
function log(message, level = 'info') {
  const prefix = { info: '[KD]', ok: '[✓]', warn: '[⚠]', error: '[✗]' }[level] || '[KD]';
  console.log(`${prefix} ${message}`);
}

function fmtBytes(bytes) {
  if (!bytes && bytes !== 0) return '—';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  return (bytes / 1e3).toFixed(1) + ' KB';
}

function fmtUptime(seconds) {
  if (!seconds && seconds !== 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  parts.push(`${s}s`);
  return parts.join(' ');
}

// Three.js Globe
async function initGlobe() {
  const container = document.getElementById('stage');

  // Renderer
  state.renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  });
  state.renderer.setSize(window.innerWidth, window.innerHeight);
  state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(state.renderer.domElement);

  // Scene
  state.scene = new THREE.Scene();

  // Camera
  state.camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 1000);
  state.camera.position.set(0, 0, 2.5);

  // Earth
  const earthGeometry = new THREE.SphereGeometry(1, 64, 64);
  const earthMaterial = new THREE.MeshStandardMaterial({
    color: 0x0a1628,
    roughness: 0.8,
    metalness: 0.2,
  });
  state.globe = new THREE.Mesh(earthGeometry, earthMaterial);
  state.scene.add(state.globe);

  // Atmosphere glow
  const atmosphereGeometry = new THREE.SphereGeometry(1.08, 64, 64);
  const atmosphereMaterial = new THREE.MeshBasicMaterial({
    color: 0x00d9ff,
    transparent: true,
    opacity: 0.08,
    side: THREE.BackSide,
  });
  const atmosphere = new THREE.Mesh(atmosphereGeometry, atmosphereMaterial);
  state.scene.add(atmosphere);

  // Particle ring (data visualization)
  const particleCount = 2000;
  const particleGeometry = new THREE.BufferGeometry();
  const positions = new Float32Array(particleCount * 3);
  const colors = new Float32Array(particleCount * 3);
  const sizes = new Float32Array(particleCount);

  for (let i = 0; i < particleCount; i++) {
    const radius = 1 + Math.random() * 0.5;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);

    positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = radius * Math.cos(phi);

    const color = new THREE.Color();
    color.setHSL(0.55 + Math.random() * 0.1, 1, 0.5 + Math.random() * 0.3);
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;

    sizes[i] = 0.5 + Math.random() * 1.5;
  }

  particleGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  particleGeometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  particleGeometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

  const particleMaterial = new THREE.PointsMaterial({
    size: 0.02,
    vertexColors: true,
    transparent: true,
    opacity: 0.6,
    sizeAttenuation: true,
  });

  state.particles = new THREE.Points(particleGeometry, particleMaterial);
  state.scene.add(state.particles);

  // Lights
  const ambientLight = new THREE.AmbientLight(0x1a2a3a, 0.6);
  state.scene.add(ambientLight);

  const sunLight = new THREE.DirectionalLight(0xffe0a0, 1.2);
  sunLight.position.set(5, 3, 5);
  state.scene.add(sunLight);

  const fillLight = new THREE.DirectionalLight(0x00d9ff, 0.4);
  fillLight.position.set(-3, -2, -3);
  state.scene.add(fillLight);

  // Grid helper (subtle)
  const gridHelper = new THREE.GridHelper(4, 40, 0x00d9ff, 0x003344);
  gridHelper.material.opacity = 0.05;
  gridHelper.material.transparent = true;
  state.scene.add(gridHelper);

  // Handle resize
  window.addEventListener('resize', onResize);

  // Interaction
  setupInteraction();

  // Start render loop
  animate();

  log('Three.js globe initialized');
}

function onResize() {
  if (!state.renderer || !state.camera) return;
  state.camera.aspect = window.innerWidth / window.innerHeight;
  state.camera.updateProjectionMatrix();
  state.renderer.setSize(window.innerWidth, window.innerHeight);
}

function setupInteraction() {
  const stage = document.getElementById('stage');
  let isDragging = false;
  let dragStart = { x: 0, y: 0 };
  let rotationStart = { x: 0, y: 0 };

  stage.addEventListener('pointerdown', (e) => {
    isDragging = true;
    dragStart = { x: e.clientX, y: e.clientY };
    rotationStart = { x: state.globe.rotation.y, y: state.globe.rotation.x };
    stage.classList.add('dragging');
    stage.setPointerCapture(e.pointerId);
  });

  window.addEventListener('pointermove', (e) => {
    if (!isDragging) return;
    const dx = (e.clientX - dragStart.x) * 0.005;
    const dy = (e.clientY - dragStart.y) * 0.005;
    state.globe.rotation.y = rotationStart.x - dx;
    state.globe.rotation.x = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, rotationStart.y - dy));
    state.particles.rotation.y = state.globe.rotation.y;
    state.particles.rotation.x = state.globe.rotation.x;
  });

  window.addEventListener('pointerup', () => {
    if (isDragging) {
      isDragging = false;
      stage.classList.remove('dragging');
    }
  });

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    state.camera.position.z = Math.max(1.5, Math.min(5, state.camera.position.z + e.deltaY * 0.002));
  }, { passive: false });
}

function animate() {
  state.animationId = requestAnimationFrame(animate);

  // Subtle rotation
  if (state.globe) {
    state.globe.rotation.y += 0.0001;
    if (state.particles) {
      state.particles.rotation.y += 0.00015;
    }
  }

  state.renderer.render(state.scene, state.camera);
}

// Clock
function updateClock() {
  const now = new Date();
  if (els.clockTime) {
    els.clockTime.textContent = now.toLocaleTimeString('en-GB', { hour12: false });
  }
  if (els.clockDate) {
    els.clockDate.textContent = now.toLocaleDateString('en-GB', {
      weekday: 'short', month: 'short', day: 'numeric',
    });
  }
}

// WebSocket connection
function connectWebSocket() {
  if (state.closing) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = websocketUrl(window.location, sessionStorage.getItem('jarvis_token') || '');

  try {
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
      log('WebSocket connected');
    };

    state.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWebSocketMessage(msg);
      } catch (e) {
        log('WS message parse error: ' + e.message, 'warn');
      }
    };

    state.ws.onclose = event => {
      if (event.code === 4001 || event.code === 1008) { expireSession(); return; }
      if (state.closing) return;
      log('WebSocket disconnected, reconnecting in 3s...');
      setTimeout(connectWebSocket, 3000);
    };

    state.ws.onerror = (e) => {
      log('WebSocket error', 'warn');
    };
  } catch (e) {
    log('WebSocket connection failed: ' + e.message, 'error');
    setTimeout(connectWebSocket, 5000);
  }
}

function handleWebSocketMessage(msg) {
  switch (msg.type) {
    case 'log':
      showCommandResult({text: `${msg.speaker}: ${msg.text}`});
      break;
    case 'status':
      showNotification({title: 'ASSISTANT', text: msg.state});
      break;
    case 'telemetry':
      state.telemetry = msg.data;
      updateTelemetryUI(msg.data);
      break;
    case 'agent_status':
      updateAgentList(msg.data);
      break;
    case 'command_result':
      showCommandResult(msg.data);
      break;
    case 'notification':
      showNotification(msg.data);
      break;
    case 'auth_ok':
      log('Authenticated');
      break;
    case 'auth_fail':
      log('Authentication failed', 'warn');
      break;
  }
}

function updateTelemetryUI(data) {
  if (!data) return;

  const metrics = telemetryMetrics(data);
  for (const key of ['cpu', 'gpu', 'vram', 'ram']) {
    if (els[`${key}Val`]) els[`${key}Val`].textContent = metrics[key];
  }
  if (els.modelVal && data.model) {
    els.modelVal.textContent = data.model;
  }
  if (els.latencyVal && data.latency !== undefined) {
    els.latencyVal.textContent = `${data.latency} ms`;
  }
  if (els.sysUptime && data.uptime !== undefined) {
    els.sysUptime.textContent = fmtUptime(data.uptime);
  }
  if (els.sysProcs && data.processes !== undefined) {
    els.sysProcs.textContent = data.processes;
  }
  if (els.sysOs && data.os) {
    els.sysOs.textContent = data.os;
  }
  if (els.sysKernel && data.kernel) {
    els.sysKernel.textContent = data.kernel;
  }
  if (els.infModel && data.infModel) {
    els.infModel.textContent = data.infModel;
  }
  if (els.infTps && data.tokensPerSec !== undefined) {
    els.infTps.textContent = data.tokensPerSec.toFixed(1);
  }
  if (els.infCtx && data.contextPercent !== undefined) {
    els.infCtx.textContent = `${data.contextPercent}%`;
  }
  if (els.infQueue && data.queueDepth !== undefined) {
    els.infQueue.textContent = data.queueDepth;
  }
}

function featureStatus(feature) {
  if (!feature.valid) return 'ERROR';
  return feature.enabled ? 'ACTIVE' : 'DISABLED';
}

function updateFeatureList(payload) {
  if (!els.featureList) return;
  const features = payload?.features || [];
  if (!features.length) {
    els.featureList.textContent = payload?.total === 0
      ? 'No functions discovered'
      : 'Function inventory unavailable';
    return;
  }
  els.featureList.innerHTML = features.map(feature => `
    <div style="margin:4px 0;display:flex;justify-content:space-between;gap:8px;">
      <span style="color:var(--amber);overflow:hidden;text-overflow:ellipsis;">${escapeHtml(feature.name)}</span>
      <span style="color:${feature.valid && feature.enabled ? 'var(--amber)' : 'var(--red)'};flex:none;">${escapeHtml(featureStatus(feature))}</span>
    </div>
  `).join('');
}

async function loadFeatures() {
  try {
    const payload = await apiRequest('/features');
    updateFeatureList(payload);
    state.features = payload.features || [];
  } catch (error) {
    if (els.featureList) els.featureList.textContent = 'Function inventory unavailable';
    log('Feature inventory unavailable: ' + error.message, 'warn');
  }
}

function showFeatureCatalog() {
  const features = state.features || [];
  if (!features.length) {
    openDetail('ALL FUNCTIONS', 'No functions discovered yet.');
    return;
  }
  const content = features.map(feature => {
    const description = escapeHtml(feature.description || 'No description provided.');
    const error = feature.error ? `<div style="color:var(--red);">${escapeHtml(feature.error)}</div>` : '';
    return `<div style="margin-bottom:14px;border-bottom:1px solid var(--amber-dim);padding-bottom:10px;">
      <div style="display:flex;justify-content:space-between;gap:8px;">
        <strong style="color:var(--amber-bright);">${escapeHtml(feature.name)}</strong>
        <span style="color:${feature.valid && feature.enabled ? 'var(--amber)' : 'var(--red)'};">${escapeHtml(featureStatus(feature))}</span>
      </div>
      <div style="color:var(--text-dim);font-size:10px;">${escapeHtml(String(feature.kind || 'function').toUpperCase())} · ${escapeHtml(feature.file || '')}</div>
      <div style="margin-top:5px;line-height:1.45;">${description}</div>
      ${error}
    </div>`;
  }).join('');
  openDetail(`ALL FUNCTIONS (${features.length})`, content);
}

function updateAgentList(agents) {
  if (!els.agentList) return;
  if (!agents || agents.length === 0) {
    els.agentList.textContent = 'No active agents';
    return;
  }
  els.agentList.innerHTML = agents.map(a =>
    `<div style="margin:4px 0;display:flex;justify-content:space-between;">
      <span style="color:var(--amber);">${escapeHtml(a.name)}</span>
      <span style="color:var(--text-dim);">${escapeHtml(a.status)}</span>
    </div>`
  ).join('');
}

// REST API helpers
async function apiRequest(endpoint, options = {}) {
  const url = `${CONFIG.apiBase}${endpoint}`;
  const defaults = {
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${sessionStorage.getItem('jarvis_token') || ''}` },
    credentials: 'include',
  };
  const res = await fetch(url, { ...defaults, ...options });
  if (res.status === 401) { expireSession(); throw new Error('Pairing expired'); }
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

async function sendCommand(text) {
  return apiRequest('/command', {method: 'POST', body: commandBody(text)});
}

function setupDock() {
  const report = error => showNotification({title: 'Request failed', text: error.message});
  els.micBtn.textContent = 'WAKE ASSISTANT';
  els.micBtn.addEventListener('click', () => apiRequest('/wake', {method: 'POST'}).catch(report));
  els.stopBtn.hidden = true;
  // There is no server emergency-stop API; never claim to have stopped operations.
  els.eStopBtn.textContent = 'SIGN OUT';
  els.eStopBtn.addEventListener('click', () => {
    sessionStorage.removeItem('jarvis_token'); location.replace('/login');
  });
  const send = async () => {
    const text = els.cmdInput.value.trim();
    if (!text) return;
    try { await sendCommand(text); els.cmdInput.value = ''; showNotification({title: 'QUEUED', text}); }
    catch (error) { report(error); }
  };
  els.sendBtn.addEventListener('click', send);
  els.cmdInput.addEventListener('keydown', event => { if (event.key === 'Enter') send(); });
  els.screenBtn.addEventListener('click', async () => {
    try {
      const result = await apiRequest('/screen');
      openDetail('DESKTOP', '');
      const image = document.createElement('img');
      image.src = result.image; image.alt = 'Desktop screenshot'; image.style.width = '100%';
      els.detailContent.appendChild(image);
    } catch (error) { report(error); }
  });
  els.cameraBtn.textContent = 'HAND GESTURES: OFF';
  els.cameraBtn.setAttribute('aria-pressed', 'false');
  state.stopGestures = installGestures(els.cameraBtn, (action, args) => {
    if (!state.globe) return;
    if (action === 'rotate') {
      state.globe.rotation.y += THREE.MathUtils.degToRad(args[0]);
      state.globe.rotation.x += THREE.MathUtils.degToRad(args[1]);
    } else if (action === 'zoom') state.camera.position.z = Math.max(1.5, Math.min(5, state.camera.position.z - args[0]));
    else if (action === 'pan') { state.scene.position.x += args[0]; state.scene.position.y += args[1]; }
    else if (action === 'reset') { state.globe.rotation.set(0, 0, 0); state.scene.position.set(0, 0, 0); state.camera.position.set(0, 0, 2.5); }
    state.particles.rotation.copy(state.globe.rotation);
  }, text => showNotification({title: 'GESTURES', text}));
  els.termBtn.textContent = 'CLASSIC CONTROLS';
  els.termBtn.addEventListener('click', () => { location.href = '/static/app.html'; });
  els.videoBtn.addEventListener('click', () => {
    els.modeBtns.forEach(other => other.classList.remove('primary'));
    showVideoPlayer();
  });

  // ── Media player ─────────────────────────────────────────────────────
  state.video = { playing: false, muted: true, source: '', title: '' };

  function showVideoPlayer() {
    if (!els.detailPanel) return;
    els.detailTitle.textContent = 'MEDIA PLAYER';
    const mutedLabel = state.video.muted ? '🔇 MUTED' : '🔊 SOUND ON';
    const playingLabel = state.video.playing ? 'PLAYING' : 'STOPPED';
    els.detailContent.innerHTML = `
      <p style="color:var(--text-dim);margin-bottom:16px;line-height:1.6;">
        Play video on the assistant display. Starts muted — unmute only when you want audio.
      </p>
      <div style="border:1px solid var(--amber-dim);border-radius:6px;padding:16px;margin-bottom:16px;background:rgba(255,170,0,0.04);">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <strong style="color:var(--amber-bright);">STATUS</strong>
          <span style="color:${state.video.playing ? 'var(--amber)' : 'var(--text-dim)'};font-weight:bold;">${playingLabel}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <strong style="color:var(--amber-bright);">SOURCE</strong>
          <span style="color:var(--text-dim);font-size:10px;overflow:hidden;text-overflow:ellipsis;">${state.video.source || '—'}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <strong style="color:var(--amber-bright);">AUDIO</strong>
          <span style="color:${state.video.muted ? 'var(--text-dim)' : 'var(--amber)'};font-weight:bold;">${mutedLabel}</span>
        </div>
      </div>
      <div style="display:flex;gap:8px;">
        <button id="vidPlay" class="dock-btn" style="flex:1;">${state.video.playing ? '■ STOP' : '▶ PLAY'}</button>
        <button id="vidMute" class="dock-btn" style="flex:1;">${mutedLabel}</button>
      </div>
      <div style="margin-top:10px;">
        <label style="color:var(--text-dim);font-size:10px;display:block;margin-bottom:4px;">YouTube link, file path, or video URL</label>
        <input type="text" id="vidSource" class="dock-input" placeholder="https://youtube.com/watch?v=… or ~/Videos/clip.mp4" style="width:100%;">
      </div>
    `;
    const vidPlay = document.getElementById('vidPlay');
    const vidMute = document.getElementById('vidMute');
    const vidSource = document.getElementById('vidSource');
    if (vidPlay) vidPlay.addEventListener('click', async () => {
      if (state.video.playing) {
        await sendCommand('video_player stop');
      } else {
        const src = vidSource.value.trim();
        if (!src) { showNotification({title: 'Media', text: 'Enter a video source first.'}); return; }
        await sendCommand(`video_player play ${src}`);
      }
      closeDetail();
    });
    if (vidMute) vidMute.addEventListener('click', async () => {
      await sendCommand(`video_player ${state.video.muted ? 'unmute' : 'mute'}`);
    });
    if (vidSource) vidSource.addEventListener('keydown', e => { if (e.key === 'Enter') vidPlay.click(); });
    els.detailPanel.classList.add('open');
    els.detailPanel.setAttribute('aria-hidden', 'false');
    state.detailPanelOpen = true;
  }

  const panels = {
    command: ['COMMAND CENTER', 'Type a request below. Replies arrive from the paired assistant.'],
    neural: ['NEURAL CORE', 'Inference details are available in the desktop provider settings.'],
    agents: ['AGENT OPS', 'Agent operations run through assistant commands; no separate agent-status feed is configured.'],
    memory: ['MEMORY', 'Ask the assistant to search or update its knowledge base using the command field.'],
    desktop: ['DESKTOP', 'Use SCREEN to capture the paired desktop.'],
    security: ['SECURITY', 'This session uses server-issued pairing authentication. SIGN OUT clears this browser session.'],
    studio: ['3D STUDIO', 'Drag to rotate, scroll to zoom, or enable HAND GESTURES. Point to rotate, two pinches to zoom, open palms to pan, fist to reset.'],
  };
  els.modeBtns.forEach(button => button.addEventListener('click', () => {
    els.modeBtns.forEach(other => other.classList.remove('primary'));
    button.classList.add('primary');
    if (button.dataset.mode === 'features') {
      showFeatureCatalog();
    } else {
      openDetail(...panels[button.dataset.mode]);
    }
  }));
  els.closeBtn.addEventListener('click', closeDetail);
  els.detailAction1.hidden = true; els.detailAction2.hidden = true;
}

// Detail panel
function openDetail(title, description, actions = []) {
  if (!els.detailPanel) return;
  els.detailTitle.textContent = title;
  els.detailContent.innerHTML = `
    <p style="color:var(--text-dim);margin-bottom:16px;line-height:1.6;">${description}</p>
    <div style="border-top:1px solid var(--amber-dim);padding-top:16px;">
      <h4 style="color:var(--amber-bright);font-family:Orbitron;font-size:11px;margin-bottom:8px;">ACTIONS</h4>
      <div id="detailActionsList"></div>
    </div>
  `;
  const actionsList = document.getElementById('detailActionsList');
  if (actionsList) {
    actions.forEach((action, i) => {
      const btn = document.createElement('button');
      btn.className = 'dock-btn';
      btn.style.width = '100%';
      btn.style.marginBottom = '8px';
      btn.textContent = action.label;
      btn.addEventListener('click', () => {
        action.action();
        closeDetail();
      });
      actionsList.appendChild(btn);
    });
  }
  els.detailPanel.classList.add('open');
  els.detailPanel.setAttribute('aria-hidden', 'false');
  state.detailPanelOpen = true;
}

function closeDetail() {
  if (!els.detailPanel) return;
  els.detailPanel.classList.remove('open');
  els.detailPanel.setAttribute('aria-hidden', 'true');
  state.detailPanelOpen = false;
}

// Notifications
function showNotification(data) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position:fixed; bottom:100px; right:20px; z-index:100;
    background:var(--panel-bg); border:1px solid var(--amber-dim);
    padding:12px 16px; font-size:11px; font-family:'Share Tech Mono',monospace;
    color:var(--amber-bright); box-shadow:0 4px 24px rgba(0,0,0,0.6);
    animation:slideIn 0.3s ease;
  `;
  toast.innerHTML = `<strong>${escapeHtml(data.title)}</strong><br><span style="color:var(--text-dim);">${escapeHtml(data.text)}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function showCommandResult(result) {
  const output = result.output || result.text || JSON.stringify(result, null, 2);
  openDetail('COMMAND RESULT', `<pre style="color:var(--amber);font-family:monospace;font-size:10px;white-space:pre-wrap;max-height:300px;overflow:auto;">${escapeHtml(output)}</pre>`);
}

// Dedicated authenticated stream, with bounded reconnect and HTTP fallback.
function telemetryStatus(text) {
  document.getElementById('telemetryStatus').textContent = text;
}

function expireSession() {
  state.closing = true;
  clearTimeout(state.telemetryRetry);
  sessionStorage.removeItem('jarvis_token');
  state.telemetrySocket?.close();
  state.ws?.close();
  telemetryStatus('PAIRING EXPIRED — SIGN IN AGAIN');
  location.replace('/login');
}

function connectTelemetry() {
  if (state.closing) return;
  clearTimeout(state.telemetryRetry);
  if (state.telemetrySocket) {
    state.telemetrySocket.onclose = null;
    state.telemetrySocket.close();
  }
  telemetryStatus('TELEMETRY CONNECTING');
  const socket = new WebSocket(websocketUrl(location, sessionStorage.getItem('jarvis_token') || '', '/ws/telemetry'));
  state.telemetrySocket = socket;
  socket.onmessage = event => {
    try {
      const data = JSON.parse(event.data);
      updateTelemetryUI(data);
      state.telemetryLastSeen = Date.now();
      state.telemetryFailures = 0;
      telemetryStatus(data.status === 'ok' ? 'TELEMETRY LIVE' : 'TELEMETRY PARTIAL — SOME METRICS UNAVAILABLE');
    } catch { telemetryStatus('TELEMETRY INVALID — WAITING FOR UPDATE'); }
  };
  socket.onerror = () => {
    telemetryStatus('TELEMETRY ERROR — RETRYING');
    const delay = Math.min(30000, 1000 * 2 ** Math.min(state.telemetryFailures || 0, 5));
    state.telemetryFailures = (state.telemetryFailures || 0) + 1;
    state.telemetryRetry = setTimeout(connectTelemetry, delay);
  };
  socket.onclose = event => {
    if (state.closing) return;
    if (event.code === 4001 || event.code === 1008) { expireSession(); return; }
    telemetryStatus('TELEMETRY OFFLINE — RETRYING');
    const delay = Math.min(30000, 1000 * 2 ** Math.min(state.telemetryFailures || 0, 5));
    state.telemetryFailures = (state.telemetryFailures || 0) + 1;
    state.telemetryRetry = setTimeout(connectTelemetry, delay);
  };
}

async function pollTelemetry() {
  if (state.closing || state.telemetryPolling) return;
  if (state.telemetrySocket?.readyState === WebSocket.OPEN && Date.now() - (state.telemetryLastSeen || 0) < 5000) return;
  state.telemetryPolling = true;
  telemetryStatus('TELEMETRY STALE — CHECKING HTTP');
  try {
    const data = await apiRequest('/telemetry');
    if (!state.closing) {
      updateTelemetryUI(data);
      telemetryStatus(data.status === 'ok' ? 'TELEMETRY HTTP FALLBACK' : 'TELEMETRY HTTP — PARTIAL');
    }
  } catch {
    if (!state.closing) {
      updateTelemetryUI({});
      telemetryStatus('TELEMETRY UNAVAILABLE — RETRYING');
    }
  } finally { state.telemetryPolling = false; }
}

// Main initialization
async function init() {
  if (!sessionStorage.getItem('jarvis_token')) { location.replace('/login'); return; }
  log('KD Dashboard initializing...');
  cacheElements();
  try { await initGlobe(); } catch (error) { log('3D unavailable: ' + error.message, 'warn'); }
  setupDock();
  connectWebSocket();
  connectTelemetry();
  document.getElementById('telemetryReconnect').addEventListener('click', connectTelemetry);

  // Start clock
  updateClock();
  state.clockTimer = setInterval(updateClock, CONFIG.clockInterval);

  // Start telemetry polling (backup)
  state.telemetryTimer = setInterval(pollTelemetry, CONFIG.telemetryInterval);

  // Initial telemetry and live function inventory
  await Promise.all([pollTelemetry(), loadFeatures()]);

  // Check for existing auth
  const token = sessionStorage.getItem('jarvis_token') || localStorage.getItem('jarvis_token');
  if (!token) {
    log('No auth token found');
  }

  log('KD Dashboard ready');
}

// Cleanup
window.addEventListener('beforeunload', () => {
  state.closing = true;
  state.stopGestures?.();
  clearTimeout(state.telemetryRetry);
  state.telemetrySocket?.close();
  if (state.animationId) cancelAnimationFrame(state.animationId);
  if (state.telemetryTimer) clearInterval(state.telemetryTimer);
  if (state.clockTimer) clearInterval(state.clockTimer);
  if (state.ws) state.ws.close();
});

// Start
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

// CSS animations for notifications
const style = document.createElement('style');
style.textContent = `
  @keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
  }
  @keyframes slideOut {
    from { transform: translateX(0); opacity: 1; }
    to { transform: translateX(100%); opacity: 0; }
  }
`;
document.head.appendChild(style);