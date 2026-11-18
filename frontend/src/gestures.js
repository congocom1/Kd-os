/** Opt-in camera frames go only to the authenticated local dashboard server. */
export function installGestures(button, apply, notify) {
  let stream, socket, timer, video, enabled = false;
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = 240;
  const stop = () => {
    enabled = false;
    clearTimeout(timer);
    if (socket) { socket.onclose = null; socket.close(); socket = null; }
    stream?.getTracks().forEach(track => track.stop());
    stream = null;
    if (video) video.srcObject = null;
    button.textContent = 'HAND GESTURES: OFF';
    button.setAttribute('aria-pressed', 'false');
  };
  const sendFrame = () => {
    if (!enabled || socket?.readyState !== WebSocket.OPEN) return;
    const ctx = canvas.getContext('2d');
    ctx.save(); ctx.translate(320, 0); ctx.scale(-1, 1);
    ctx.drawImage(video, 0, 0, 320, 240); ctx.restore();
    canvas.toBlob(blob => {
      if (enabled && socket?.readyState === WebSocket.OPEN && blob) socket.send(blob);
    }, 'image/jpeg', 0.65);
  };
  button.addEventListener('click', async () => {
    if (enabled) { stop(); return; }
    if (!confirm('Enable hand tracking? Camera frames will be sent to this local dashboard server for processing. They are not saved.')) return;
    enabled = true;
    button.textContent = 'STARTING HAND TRACKING…';
    try {
      if (!window.isSecureContext || !navigator.mediaDevices) throw new Error('Camera access requires HTTPS or localhost.');
      stream = await navigator.mediaDevices.getUserMedia({video: {width: 320, height: 240}, audio: false});
      if (!enabled) { stream.getTracks().forEach(track => track.stop()); return; }
      video = document.createElement('video');
      video.muted = true; video.playsInline = true; video.srcObject = stream;
      await video.play();
      if (!enabled) { stop(); return; }
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${location.host}/ws/gestures?token=${encodeURIComponent(sessionStorage.getItem('jarvis_token') || '')}`);
      socket.onmessage = event => {
        const message = JSON.parse(event.data);
        if (message.ready) {
          button.textContent = 'HAND GESTURES: ON';
          button.setAttribute('aria-pressed', 'true');
        }
        for (const command of message.events || []) apply(command.action, command.args);
        timer = setTimeout(sendFrame, 70);
      };
      socket.onerror = () => { notify('Hand tracking connection failed'); stop(); };
      socket.onclose = () => { notify('Hand tracking stopped'); stop(); };
    } catch (error) { notify(error.message); stop(); }
  });
  window.addEventListener('pagehide', stop);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  return stop;
}