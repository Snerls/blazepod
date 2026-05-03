/**
 * Connect ONE pod and hold the connection silently. Print a heartbeat every
 * 2 seconds; print the moment the pod disconnects. Tests whether Pod.connect's
 * static-auth path produces a stable session or whether the pod kills us.
 *
 * Usage: node tests/hold_one.mjs [--hold-s 60] [--write-color]
 *   --write-color   periodically toggle red so the pod sees activity
 */

import { bluetooth } from 'webbluetooth';
if (!('bluetooth' in navigator)) {
  Object.defineProperty(navigator, 'bluetooth', { value: bluetooth, configurable: true });
}
const _ls = new Map();
globalThis.localStorage = {
  getItem: (k) => (_ls.has(k) ? _ls.get(k) : null),
  setItem: (k, v) => _ls.set(k, String(v)),
  removeItem: (k) => _ls.delete(k),
  clear: () => _ls.clear(),
};

const args = process.argv.slice(2);
const HOLD_S = parseFloat(args[args.indexOf('--hold-s') + 1]) || 60;
const WRITE = args.includes('--write-color');

const { Pod, pickPod } = await import('../web/js/pod.js');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = () => new Date().toISOString().slice(11, 23);
const log = (m) => console.log(`${fmt()}  ${m}`);

const t0 = performance.now();
const elapsed = () => `+${((performance.now() - t0) / 1000).toFixed(1)}s`;

const device = await pickPod();
log(`picked ${device.id}`);

const pod = new Pod(device);

let disconnectedAt = null;
device.addEventListener('gattserverdisconnected', () => {
  disconnectedAt = elapsed();
  log(`>>> DISCONNECTED at ${disconnectedAt}`);
});

await pod.connect();
log(`connected ${elapsed()}  isConnected=${pod.isConnected}`);

let tapN = 0;
pod.onTap((_p, ev) => { tapN++; log(`TAP #${tapN} state=0x${ev.state.toString(16).padStart(2,'0')} ms=${ev.elapsedMs}`); });

const tEnd = performance.now() + HOLD_S * 1000;
let beat = 0;
while (performance.now() < tEnd) {
  await sleep(2000);
  beat++;
  if (disconnectedAt) {
    log(`heartbeat #${beat} ${elapsed()}  STATE: disconnected (since ${disconnectedAt})`);
    continue;
  }
  log(`heartbeat #${beat} ${elapsed()}  STATE: ${pod.isConnected ? 'connected' : 'NOT CONNECTED'}`);
  if (WRITE) {
    try {
      await pod.setColor(0, 80, 0);
      await sleep(80);
      await pod.turnOff();
    } catch (e) { log(`  write failed: ${e.message}`); }
  }
}

log(`\nfinal: isConnected=${pod.isConnected}  taps=${tapN}  disconnect=${disconnectedAt || 'none'}`);
try { await pod.disconnect(); } catch {}
process.exit(0);
