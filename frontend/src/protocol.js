export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

export function commandBody(text) {
  if (typeof text !== 'string' || !text.trim()) throw new Error('Enter a command');
  return JSON.stringify({text: text.trim()});
}

export function websocketUrl(location, token, path = '/ws') {
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${path}?token=${encodeURIComponent(token)}`;
}

export function telemetryMetrics(data = {}) {
  const system = data.system || {};
  const gpu = data.gpu || {};
  const number = (value, suffix) => Number.isFinite(value) ? `${value.toFixed(1)}${suffix}` : 'Unavailable';
  return {
    cpu: number(system.cpu_percent, '%'),
    gpu: number(gpu.utilization_gpu, '%'),
    vram: number(gpu.memory_used_mb, ' MiB'),
    ram: number(system.memory_percent, '%'),
  };
}