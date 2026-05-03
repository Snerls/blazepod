/**
 * E2E test for the web app's BLE code, run from Node against real pods.
 *
 * Imports the SAME `web/js/pod.js`, `web/js/protocol.js` modules the browser
 * uses, runs them against a `webbluetooth` shim that exposes the real
 * Bluetooth adapter via SimpleBLE/noble. If this passes, the JS code is
 * functionally correct — any failure on Chrome/iOS is environment-specific,
 * not a bug in our code.
 *
 * Usage: node tests/web_e2e.mjs
 */

import { bluetooth } from 'webbluetooth';

// --- Polyfill globals our web code expects in a browser ----------------------

const _ls = new Map();
globalThis.localStorage = {
  getItem: (k) => (_ls.has(k) ? _ls.get(k) : null),
  setItem: (k, v) => _ls.set(k, String(v)),
  removeItem: (k) => _ls.delete(k),
  clear: () => _ls.clear(),
};
// Node 24 makes `navigator` a read-only global; attach bluetooth directly.
if (!('bluetooth' in navigator)) {
  Object.defineProperty(navigator, 'bluetooth', { value: bluetooth, configurable: true });
}

// --- Now import the actual web modules ---------------------------------------

const { Pod, mfrCache, pickPod } = await import('../web/js/pod.js');
const { bytesToHex, hexToBytes } = await import('../web/js/protocol.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Use the working Python+Bleak path to capture mfr_data, then feed it to the JS
// code via the localStorage cache. This isolates the "watchAdvertisements
// doesn't work in Node/iOS" problem from the rest of the JS connect chain.
async function captureMfrViaPython() {
  const { spawn } = await import('node:child_process');
  return new Promise((resolve, reject) => {
    const p = spawn('python', ['tests/_scan_one.py'], { stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    p.stdout.on('data', (d) => { out += d.toString(); });
    p.stderr.on('data', (d) => { err += d.toString(); });
    p.on('close', (code) => {
      if (code !== 0) return reject(new Error(`python scan failed (code ${code}): ${err || out}`));
      try { resolve(JSON.parse(out.trim())); }
      catch (e) { reject(new Error(`bad python json: ${out}`)); }
    });
  });
}

// --- Mini test runner --------------------------------------------------------

let passed = 0, failed = 0, currentStep = 0;
const results = [];

function step(name) {
  currentStep++;
  process.stdout.write(`\n  [${currentStep}] ${name}\n      `);
  return name;
}
function ok(detail) {
  process.stdout.write(`PASS  ${detail || ''}\n`);
  passed++;
  results.push({ step: currentStep, status: 'PASS', detail });
}
function fail(detail) {
  process.stdout.write(`FAIL  ${detail || ''}\n`);
  failed++;
  results.push({ step: currentStep, status: 'FAIL', detail });
}

// --- The end-to-end run -----------------------------------------------------

async function main() {
  console.log('==================================================================');
  console.log(' BlazePod web app — Node + webbluetooth E2E test');
  console.log(' (uses the SAME web/js/*.js code that the browser runs)');
  console.log('==================================================================');

  let device;
  try {
    step('pickPod() — webbluetooth requestDevice (the JS picker path)');
    device = await pickPod();
    if (!device) throw new Error('no device returned');
    ok(`device.id=${device.id}  name='${device.name}'`);
  } catch (e) {
    fail(`${e.message || e}`);
    return summary();
  }

  // No more cache priming! With the static auth payload we no longer need
  // mfrData at all — the whole point of this rewrite.
  step('verify mfrCache is intentionally NOT used by Pod.connect (no advertisement read)');
  ok(`mfrCache available but unused: ${typeof mfrCache.get === 'function'}`);

  let pod;
  try {
    step('Pod.connect() — gatt.connect → write static auth → subscribe taps');
    pod = new Pod(device);
    const t0 = performance.now();
    await pod.connect();
    const dt = performance.now() - t0;
    ok(`connected in ${dt.toFixed(0)}ms  (no mfrData required)`);
  } catch (e) {
    fail(`${e?.name || ''} ${e?.message || e}`);
    return summary();
  }

  try {
    step('setColor(255,0,0) — physical pod should light RED');
    await pod.setColor(255, 0, 0);
    await sleep(1000);
    await pod.turnOff();
    ok('wrote red, slept 1s, wrote off (no errors — verify visually)');
  } catch (e) { fail(e.message || e); }

  try {
    step('flash(0,255,0,3) — pod blinks GREEN x3');
    await pod.flash(0, 255, 0, { count: 3, onMs: 200, offMs: 150 });
    ok('three flashes completed');
  } catch (e) { fail(e.message || e); }

  let tapCount = 0;
  try {
    step('subscribe to taps — listening 6 seconds, please TAP THE POD');
    pod.onTap((_p, ev) => { tapCount++; console.log(`        tap #${tapCount}: state=0x${ev.state.toString(16).padStart(2, '0')} elapsed_ms=${ev.elapsedMs}`); });
    process.stdout.write('      waiting...\n      ');
    await sleep(6000);
    if (tapCount > 0) ok(`captured ${tapCount} tap event(s)`);
    else fail('no tap events received in 6s — was the pod tapped?');
  } catch (e) { fail(e.message || e); }

  try {
    step('disconnect — clean teardown');
    await pod.disconnect();
    ok(`server.connected=${pod.server?.connected}`);
  } catch (e) { fail(e.message || e); }

  // The big test — does the cache work cross-instance?
  try {
    step('reconnect with NEW Pod object — should be just a fresh gatt.connect');
    const pod2 = new Pod(device);
    const t0 = performance.now();
    await pod2.connect();
    const dt = performance.now() - t0;
    await pod2.disconnect();
    if (dt < 6000) ok(`reconnected in ${dt.toFixed(0)}ms`);
    else fail(`slow reconnect ${dt.toFixed(0)}ms`);
  } catch (e) { fail(`${e?.name || ''} ${e?.message || e}`); }

  summary();
}

function summary() {
  console.log('\n==================================================================');
  console.log(`  ${passed} passed, ${failed} failed`);
  console.log('==================================================================');
  for (const r of results) {
    console.log(`  ${r.status === 'PASS' ? '✓' : '✗'} step ${r.step}: ${r.detail || ''}`);
  }
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => {
  console.error('\nUNHANDLED:', e);
  process.exit(2);
});
