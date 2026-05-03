/**
 * Multi-pod sustained-connection / drill E2E test (Node + webbluetooth).
 *
 * Connects every nearby pod, then runs a Random-Light-style drill: cycles
 * through pods, lighting one at a time, waiting for "tap" events. Logs every
 * gattserverdisconnected event with a timestamp so we can see exactly when
 * each pod drops out — and whether it correlates with auth / writes / idle.
 *
 * Usage: node tests/drill_e2e.mjs [--count N] [--hold-s S]
 *   --count   how many pods to try to connect (default: all in range)
 *   --hold-s  total seconds to hold the connections (default: 30)
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
function arg(name, def) {
  const i = args.indexOf(name);
  return i === -1 ? def : args[i + 1];
}
const TARGET_COUNT = parseInt(arg('--count', '6'), 10);
const HOLD_S = parseFloat(arg('--hold-s', '30'));

const { Pod, pickPod } = await import('../web/js/pod.js');
const { TAP_STATE } = await import('../web/js/protocol.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = () => new Date().toISOString().slice(11, 23);
const log = (msg) => console.log(`${fmt()}  ${msg}`);

async function pickN(n) {
  const seen = new Set();
  const devices = [];
  for (let i = 0; i < n; i++) {
    log(`scanning for pod ${i + 1}/${n}…`);
    let d;
    try { d = await pickPod(); } catch (e) {
      if (e?.name === 'NotFoundError') { log('  no more pods in range'); break; }
      throw e;
    }
    if (seen.has(d.id)) {
      log(`  duplicate ${d.id}, retrying`);
      i--;
      continue;
    }
    seen.add(d.id);
    devices.push(d);
    log(`  picked: id=${d.id}  name='${d.name}'`);
  }
  return devices;
}

async function main() {
  console.log(`\n=== drill_e2e: target=${TARGET_COUNT} pods, hold=${HOLD_S}s ===\n`);

  const devices = await pickN(TARGET_COUNT);
  if (devices.length === 0) { console.error('no pods found'); process.exit(1); }
  log(`got ${devices.length} unique pods`);

  // Build Pods + listen for disconnect events
  const pods = [];
  const disconnects = [];
  for (const d of devices) {
    const pod = new Pod(d);
    d.addEventListener('gattserverdisconnected', () => {
      const t = (performance.now() - tStart).toFixed(0);
      disconnects.push({ addr: d.id, atMs: t });
      log(`  >>> DISCONNECT  ${d.id}  at +${t}ms`);
    });
    pods.push(pod);
  }

  // Connect in parallel
  log(`connecting ${pods.length} pods in parallel…`);
  const tStart = performance.now();
  const connectResults = await Promise.allSettled(pods.map(async (pod, i) => {
    const t0 = performance.now();
    try {
      await pod.connect();
      log(`  [${i+1}] CONNECTED  ${pod.address}  in ${(performance.now()-t0).toFixed(0)}ms`);
      return pod;
    } catch (e) {
      log(`  [${i+1}] FAILED     ${pod.address}  ${e.message || e}`);
      throw e;
    }
  }));
  const connected = pods.filter((_, i) => connectResults[i].status === 'fulfilled' && pods[i].isConnected);
  log(`\nconnected: ${connected.length}/${pods.length}\n`);
  if (connected.length === 0) { console.error('no successful connections'); process.exit(2); }

  // Subscribe to taps + count by pod
  const tapCounts = new Map(connected.map((p) => [p.address, 0]));
  for (const p of connected) {
    p.onTap((src, ev) => {
      tapCounts.set(src.address, (tapCounts.get(src.address) || 0) + 1);
      log(`  TAP ${src.address}  state=0x${ev.state.toString(16).padStart(2,'0')} ms=${ev.elapsedMs}`);
    });
  }

  // Sample drill: rotate through pods, light each red briefly
  log(`\nrunning rotating-light drill for ~${HOLD_S}s — TAP PODS as they light up\n`);
  const tEnd = performance.now() + HOLD_S * 1000;
  let cursor = 0, rounds = 0;
  while (performance.now() < tEnd) {
    const pod = connected[cursor % connected.length];
    cursor++; rounds++;
    if (!pod.isConnected) {
      log(`  skip (disconnected): ${pod.address}`);
      await sleep(200);
      continue;
    }
    try {
      await pod.setColor(0, 200, 0); // green
      await sleep(700);
      await pod.turnOff();
      await sleep(200);
    } catch (e) {
      log(`  setColor failed on ${pod.address}: ${e.message || e}`);
    }
  }

  // Final report
  console.log('\n=== summary ===');
  log(`rounds run:    ${rounds}`);
  log(`held for:      ${((performance.now() - tStart) / 1000).toFixed(1)}s`);
  log(`taps received: ${[...tapCounts.entries()].map(([a, n]) => `${a}=${n}`).join('  ')}`);
  log(`disconnects:   ${disconnects.length}`);
  for (const d of disconnects) log(`  - ${d.addr} @ +${d.atMs}ms`);

  // Check: any pod still connected at the end?
  const stillConnected = connected.filter((p) => p.isConnected);
  log(`still connected at end: ${stillConnected.length}/${connected.length}`);

  // Cleanup
  await Promise.allSettled(connected.map((p) => p.disconnect()));
  process.exit(disconnects.length === 0 ? 0 : 1);
}

main().catch((e) => { console.error('UNHANDLED', e); process.exit(3); });
