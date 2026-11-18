import {test} from 'node:test';
import assert from 'node:assert/strict';
import {escapeHtml, commandBody, websocketUrl, telemetryMetrics} from './protocol.js';

test('command uses server text contract', () => {
  assert.deepEqual(JSON.parse(commandBody(' hello ')), {text: 'hello'});
  assert.throws(() => commandBody(' '));
});
test('websocket authenticates at handshake', () => {
  assert.equal(websocketUrl({protocol: 'https:', host: 'localhost:8000'}, 'a+b'),
    'wss://localhost:8000/ws?token=a%2Bb');
});
test('untrusted output is escaped', () => {
  assert.equal(escapeHtml('<img src=x onerror="bad">'), '&lt;img src=x onerror=&quot;bad&quot;&gt;');
});

test('telemetry URL uses authenticated dedicated stream', () => {
  assert.equal(websocketUrl({protocol: 'https:', host: 'localhost:8001'}, 'a+b', '/ws/telemetry'),
    'wss://localhost:8001/ws/telemetry?token=a%2Bb');
});
test('telemetry missing values are unavailable, not fabricated zeroes', () => {
  assert.deepEqual(telemetryMetrics({system: {cpu_percent: 0, memory_percent: 30}, gpu: {utilization_gpu: null}}),
    {cpu: '0.0%', ram: '30.0%', gpu: 'Unavailable', vram: 'Unavailable'});
  assert.equal(telemetryMetrics({gpu: {memory_used_mb: 1024}}).vram, '1024.0 MiB');
  assert.equal(telemetryMetrics().cpu, 'Unavailable');
});