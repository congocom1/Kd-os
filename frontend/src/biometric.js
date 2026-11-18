/**
 * KD Biometric Access Module
 * Face recognition enrollment and verification for KD access
 */

// Configuration
const CONFIG = {
  enrollSamples: 5,
  recognitionThreshold: 0.55,
  detectionInterval: 340,
  profilesKey: 'kd_operator_profiles',
  activeUserKey: 'kd_active_operator',
  modelBase: 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.7/model/',
};

// State
const state = {
  mode: 'OFFLINE', // OFFLINE, SCAN, ENROLL, GRANTED
  scanning: false,
  pausedForVisibility: false,
  destroyed: false,
  video: null,
  canvas: null,
  ctx: null,
  detectionLoop: null,
  redirectTimer: null,
  currentUser: null,
};

// DOM elements
const els = {
  video: document.getElementById('video'),
  status: document.getElementById('status'),
  beginEnrollBtn: document.getElementById('beginEnrollBtn'),
  guestLink: document.getElementById('guestLink'),
  resetLink: document.getElementById('resetLink'),
  sysCore: document.getElementById('sysCore'),
  sysGpu: document.getElementById('sysGpu'),
  sysMem: document.getElementById('sysMem'),
  sysOllama: document.getElementById('sysOllama'),
};

// Face API models (lazy loaded)
let faceapi = null;
let modelsLoaded = false;

// Utility functions
function log(message, level = 'info') {
  const prefix = {
    info: '[KD]',
    ok: '[✓]',
    warn: '[⚠]',
    error: '[✗]',
  }[level] || '[KD]';
  console.log(`${prefix} ${message}`);
}

function setStatus(title, detail = '') {
  if (els.status) {
    els.status.innerHTML = detail
      ? `${title}<br><small style="color:var(--text-dim);font-weight:400;letter-spacing:1px;">${detail}</small>`
      : title;
  }
}

function fmtBytes(bytes) {
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  return (bytes / 1e3).toFixed(1) + ' KB';
}

async function loadFaceAPI() {
  if (faceapi) return faceapi;

  try {
    // Load face-api.js from CDN
    const module = await import('https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.7/dist/face-api.esm.min.js');
    faceapi = module.default || module;
    log('face-api.js loaded');
    return faceapi;
  } catch (e) {
    log('Failed to load face-api.js: ' + e.message, 'error');
    throw e;
  }
}

async function loadModels() {
  if (modelsLoaded) return;

  try {
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(CONFIG.modelBase),
      faceapi.nets.faceLandmark68Net.loadFromUri(CONFIG.modelBase),
      faceapi.nets.faceRecognitionNet.loadFromUri(CONFIG.modelBase),
      faceapi.nets.faceExpressionNet.loadFromUri(CONFIG.modelBase),
    ]);
    modelsLoaded = true;
    log('Face recognition models loaded');
  } catch (e) {
    log('Failed to load models: ' + e.message, 'error');
    throw e;
  }
}

function getProfiles() {
  try {
    const data = localStorage.getItem(CONFIG.profilesKey);
    return data ? JSON.parse(data) : [];
  } catch {
    return [];
  }
}

function saveProfiles(profiles) {
  try {
    localStorage.setItem(CONFIG.profilesKey, JSON.stringify(profiles));
    return true;
  } catch {
    return false;
  }
}

function normalizeDescriptor(desc) {
  if (!desc || !desc.length) return null;
  const arr = Array.from(desc);
  const norm = Math.sqrt(arr.reduce((s, v) => s + v * v, 0));
  return norm > 0 ? arr.map(v => v / norm) : null;
}

function distance(a, b) {
  if (!a || !b || a.length !== b.length) return Infinity;
  let sum = 0;
  for (let i = 0; i < a.length; i++) {
    const d = a[i] - b[i];
    sum += d * d;
  }
  return Math.sqrt(sum);
}

function findMatch(descriptor) {
  const profiles = getProfiles();
  let best = null;
  let bestDist = Infinity;

  for (const profile of profiles) {
    for (const saved of profile.descriptors) {
      const d = distance(descriptor, saved);
      if (d < bestDist) {
        bestDist = d;
        best = profile.name;
      }
    }
  }

  return bestDist < CONFIG.recognitionThreshold ? { name: best, distance: bestDist } : null;
}

async function startCamera() {
  if (state.video) return state.video;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
      audio: false,
    });

    state.video = els.video;
    state.video.srcObject = stream;
    await new Promise((resolve, reject) => {
      state.video.onloadedmetadata = () => {
        state.video.play().then(resolve).catch(reject);
      };
      state.video.onerror = reject;
      setTimeout(() => reject(new Error('Video load timeout')), 10000);
    });

    log('Camera started');
    return state.video;
  } catch (e) {
    log('Camera access denied: ' + e.message, 'error');
    setStatus('CAMERA DENIED', 'Enable camera permission to use biometric access');
    throw e;
  }
}

function stopCamera() {
  if (state.video?.srcObject) {
    state.video.srcObject.getTracks().forEach(t => t.stop());
    state.video.srcObject = null;
  }
}

function drawBox(box, color) {
  if (!state.ctx || !state.canvas) return;
  const { x, y, width, height } = box;
  const scaleX = state.canvas.width / state.video.videoWidth;
  const scaleY = state.canvas.height / state.video.videoHeight;
  state.ctx.strokeStyle = color;
  state.ctx.lineWidth = 2;
  state.ctx.strokeRect(x * scaleX, y * scaleY, width * scaleX, height * scaleY);
}

function drawLandmarks(landmarks, color = '#ffe0a0') {
  if (!state.ctx || !state.canvas || !landmarks) return;
  const scaleX = state.canvas.width / state.video.videoWidth;
  const scaleY = state.canvas.height / state.video.videoHeight;
  state.ctx.fillStyle = color;
  for (const pt of landmarks) {
    state.ctx.beginPath();
    state.ctx.arc(pt.x * scaleX, pt.y * scaleY, 1.5, 0, Math.PI * 2);
    state.ctx.fill();
  }
}

function isUsableFace(result) {
  return result &&
    result.detection &&
    result.detection.score > 0.85 &&
    result.landmarks &&
    result.descriptor &&
    result.descriptor.length === 128;
}

async function wait(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// Main detection loop
async function detectionLoop() {
  if (!state.scanning || state.destroyed || state.pausedForVisibility) return;

  try {
    const result = await faceapi
      .detectSingleFace(state.video, new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 }))
      .withFaceLandmarks()
      .withFaceDescriptor()
      .withFaceExpressions();

    // Clear canvas
    state.ctx.clearRect(0, 0, state.canvas.width, state.canvas.height);

    if (result && isUsableFace(result)) {
      drawBox(result.detection.box, state.mode === 'ENROLL' ? '#ffe0a0' : '#35ff8a');
      drawLandmarks(result.landmarks.positions);

      if (state.mode === 'ENROLL') {
        // Handled by enrollment function
      } else if (state.mode === 'SCAN') {
        const match = findMatch(result.descriptor);
        if (match) {
          stopDetectionLoop();
          grantAccess(match.name);
          return;
        }
      }
    }
  } catch (e) {
    // Ignore transient detection errors
  }

  if (state.scanning && !state.destroyed && !state.pausedForVisibility) {
    state.detectionLoop = setTimeout(detectionLoop, CONFIG.detectionInterval);
  }
}

function startDetectionLoop() {
  if (state.scanning) return;
  state.scanning = true;
  detectionLoop();
}

function stopDetectionLoop() {
  state.scanning = false;
  if (state.detectionLoop) {
    clearTimeout(state.detectionLoop);
    state.detectionLoop = null;
  }
}

// Enrollment flow
async function runEnrollment() {
  const name = prompt('Enter operator name:')?.trim();
  if (!name) return;

  if (els.beginEnrollBtn) {
    els.beginEnrollBtn.disabled = true;
    els.beginEnrollBtn.textContent = 'SCANNING…';
  }

  setStatus('ENROLLING', `Capturing ${CONFIG.enrollSamples} samples for "${name}"`);
  const samples = [];

  for (let i = 0; i < CONFIG.enrollSamples; i++) {
    if (state.mode !== 'ENROLL') break;

    await wait(CONFIG.detectionInterval);
    const result = await faceapi
      .detectSingleFace(state.video, new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.5 }))
      .withFaceLandmarks()
      .withFaceDescriptor();

    if (result && isUsableFace(result)) {
      const descriptor = normalizeDescriptor(result.descriptor);
      if (descriptor) {
        drawBox(result.detection.box, '#ffe0a0');
        samples.push(descriptor);
        setStatus('ENROLLING', `Sample ${samples.length} of ${CONFIG.enrollSamples}`);
      }
    } else {
      setStatus('ENROLLING', 'Face not clear — hold still and center');
      i--; // Retry this sample
    }
  }

  if (samples.length < CONFIG.enrollSamples) {
    setStatus('ENROLLMENT FAILED', 'Could not capture enough clean samples');
    log('Enrollment aborted — insufficient samples', 'warn');
    if (els.beginEnrollBtn) {
      els.beginEnrollBtn.disabled = false;
      els.beginEnrollBtn.textContent = 'BEGIN ENROLLMENT SCAN';
    }
    return;
  }

  const profiles = getProfiles();
  const duplicateIndex = profiles.findIndex(p => p.name.toLowerCase() === name.toLowerCase());
  const record = { name, descriptors: samples, enrolledAt: new Date().toISOString() };

  if (duplicateIndex >= 0) profiles[duplicateIndex] = record;
  else profiles.push(record);

  const persisted = saveProfiles(profiles);
  if (persisted) {
    log(`${duplicateIndex >= 0 ? 'Operator profile updated' : 'New operator enrolled'} — ${name}`, 'ok');
  } else {
    log('Profile saved to session only (storage unavailable)', 'warn');
    setStatus('STORAGE UNAVAILABLE', 'Profile not persisted; continuing for this session');
    await wait(650);
  }

  state.mode = 'GRANTED';
  grantAccess(name);
}

// Grant access and transition to dashboard
function grantAccess(name) {
  state.currentUser = name;
  state.mode = 'GRANTED';

  try {
    localStorage.setItem(CONFIG.activeUserKey, name);
  } catch { /* ignore */ }

  setStatus('ACCESS GRANTED', `Welcome, ${name}`);
  log(`Access granted to ${name}`, 'ok');

  // Redirect to dashboard
  state.redirectTimer = setTimeout(() => {
    // Face recognition is a local visual gate, not server authentication.
    window.location.href = '/login';
  }, 800);
}

// Start scanning for recognition
async function beginScanning() {
  if (getProfiles().length === 0) {
    setStatus('NO PROFILES', 'No operators enrolled — use enrollment or continue as guest');
    return;
  }

  state.mode = 'SCAN';
  setStatus('SCANNING', 'Present your face to the camera');
  if (els.beginEnrollBtn) {
    els.beginEnrollBtn.disabled = true;
    els.beginEnrollBtn.textContent = 'SCANNING…';
  }
  startDetectionLoop();
}

// System diagnostics
async function runDiagnostics() {
  try {
    // Core diagnostics via API
    const resp = await fetch('/api/diagnostics', { cache: 'no-store' });
    if (resp.ok) {
      const data = await resp.json();
      if (els.sysCore) els.sysCore.textContent = data.core?.status || 'OK';
      if (els.sysGpu) els.sysGpu.textContent = data.gpu?.name || '—';
      if (els.sysMem) els.sysMem.textContent = fmtBytes(data.memory?.total || 0);
      if (els.sysOllama) els.sysOllama.textContent = data.ollama?.status || '—';
    }
  } catch {
    // Silently fail - diagnostics are optional
  }
}

// Initialize
async function boot() {
  log('Boot sequence started');

  try {
    await startCamera();
    await loadFaceAPI();
    await loadModels();

    // Setup canvas for overlay
    state.canvas = document.createElement('canvas');
    state.canvas.width = state.video.videoWidth;
    state.canvas.height = state.video.videoHeight;
    state.canvas.style.position = 'absolute';
    state.canvas.style.top = '0';
    state.canvas.style.left = '0';
    state.canvas.style.width = '100%';
    state.canvas.style.height = '100%';
    state.canvas.style.pointerEvents = 'none';
    state.ctx = state.canvas.getContext('2d');
    state.video.parentElement.appendChild(state.canvas);

    // Run diagnostics
    await runDiagnostics();

    // Check for existing session
    const activeUser = localStorage.getItem(CONFIG.activeUserKey);
    if (activeUser) {
      log(`Resuming session for ${activeUser}`);
      grantAccess(activeUser);
      return;
    }

    // Enable enrollment button
    if (els.beginEnrollBtn) {
      els.beginEnrollBtn.disabled = false;
      els.beginEnrollBtn.textContent = 'BEGIN ENROLLMENT SCAN';
    }

    setStatus('READY', 'No enrolled operators — enroll or continue as guest');

    // Event listeners
    if (els.beginEnrollBtn) {
      els.beginEnrollBtn.addEventListener('click', () => {
        state.mode = 'ENROLL';
        runEnrollment();
      });
    }

    if (els.guestLink) {
      els.guestLink.addEventListener('click', () => {
        stopDetectionLoop();
        state.mode = 'GRANTED';
        setStatus('CONTINUING AS GUEST', 'Skipping biometric verification…');
        grantAccess(null);
      });
    }

    if (els.resetLink) {
      els.resetLink.addEventListener('click', () => {
        if (!confirm('Erase all registered operator profiles? This cannot be undone.')) return;
        localStorage.removeItem(CONFIG.profilesKey);
        localStorage.removeItem(CONFIG.activeUserKey);
        log('All operator profiles erased', 'warn');
        if (state.mode !== 'OFFLINE') beginScanning();
      });
    }

    // Visibility handling
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && state.scanning) {
        state.pausedForVisibility = true;
        stopDetectionLoop();
      } else if (!document.hidden && state.pausedForVisibility && state.mode === 'SCAN') {
        state.pausedForVisibility = false;
        startDetectionLoop();
      }
    });

    window.addEventListener('pagehide', () => {
      state.destroyed = true;
      stopDetectionLoop();
      clearTimeout(state.redirectTimer);
      stopCamera();
    }, { once: true });

    // Auto-start scanning if profiles exist
    if (getProfiles().length > 0) {
      await beginScanning();
    }

  } catch (e) {
    log('Boot failed: ' + e.message, 'error');
    setStatus('SYSTEM ERROR', e.message);
  }
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}