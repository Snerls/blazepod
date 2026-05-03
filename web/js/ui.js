// Screen routing + form state + drill control.

import { Pod, pickPod } from './pod.js';
import { PodManager } from './manager.js';
import {
  CustomDrill, DurationMode, LightDelay, LightsOut,
  defaultConfig, makeStats, statsSummary,
} from './drill.js';

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const manager = new PodManager();
let currentDrill = null;
let lastDrillCfg = null;       // for "Run again" of custom drill
let lastDrillKind = null;      // 'custom' | 'random' | 'sequence' | 'color_match'
let pollTimer = null;
let wakeLock = null;

// ---------- Screen routing ----------

function show(id) {
  $$('.screen').forEach((s) => s.classList.remove('active'));
  $('#screen-' + id).classList.add('active');
  if (id === 'menu')   refreshMenu();
  if (id === 'config') refreshConfig();
  // Top of page on screen change (matters on mobile)
  window.scrollTo(0, 0);
}

// ---------- Toast ----------

const toastEl = $('#toast');
let toastTimer;
function toast(msg, kind) {
  toastEl.textContent = msg;
  toastEl.className = 'toast ' + (kind || '');
  toastEl.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.style.display = 'none'; }, 3500);
}

// ---------- Pods screen ----------

function refreshPodList() {
  const list = $('#pods-list');
  list.innerHTML = '';
  const pods = manager.values();
  if (pods.length === 0) {
    $('#pods-status').textContent = 'No pods yet. Tap "+ Add pod" and pick one from the list.';
  } else {
    $('#pods-status').textContent = `${pods.length} pod(s) connected.`;
  }
  for (const pod of pods) {
    const row = document.createElement('div');
    row.className = 'pod-item ' + (pod.isConnected ? 'connected' : 'failed');
    row.innerHTML = `
      <div>
        <div class="name">${escapeHtml(pod.name)}</div>
        <div class="addr">${pod.address}</div>
      </div>
      <div class="pod-actions">
        <button class="secondary flash-btn">Flash</button>
        <button class="secondary remove-btn">Remove</button>
      </div>`;
    row.querySelector('.flash-btn').onclick = async () => {
      try { await pod.flash(255, 0, 0, { count: 3 }); } catch (e) { toast(`Flash failed: ${e.message}`, 'error'); }
    };
    row.querySelector('.remove-btn').onclick = async () => {
      manager.remove(pod.address);
      refreshPodList();
      refreshPodControls();
    };
    list.appendChild(row);
  }
  refreshPodControls();
}

function refreshPodControls() {
  const n = manager.size;
  $('#btn-identify').disabled = n === 0;
  $('#btn-disconnect').disabled = n === 0;
  $('#btn-go-menu').disabled = n === 0;
}

$('#btn-add-pod').onclick = async () => {
  try {
    const device = await pickPod();
    if (manager.pods.has(device.id)) {
      toast(`${device.name || device.id} already added`, 'warn');
      return;
    }
    const pod = new Pod(device);
    toast(`Connecting to ${device.name || 'pod'}…`);
    await pod.connect();
    manager.add(pod);
    toast(`Connected ${pod.name}`);
    try { await pod.flash(0, 200, 0, { count: 1, onMs: 250 }); } catch {}
    refreshPodList();
  } catch (e) {
    if (e?.name === 'NotFoundError') return; // user cancelled the picker
    toast(`Add failed: ${e.message}`, 'error');
    console.error(e);
  }
};

$('#btn-identify').onclick = async () => {
  if (manager.size === 0) return;
  $('#btn-identify').disabled = true;
  try {
    await manager.identifyEach({
      onPod: (p) => toast(`Flashing ${p.name} (${p.address.slice(0, 8)}…)`),
    });
    toast('Identify complete');
  } catch (e) { toast(`Identify failed: ${e.message}`, 'error'); }
  finally { refreshPodControls(); }
};

$('#btn-disconnect').onclick = async () => {
  await manager.disconnectAll();
  refreshPodList();
};

$('#btn-go-menu').onclick = () => show('menu');

// ---------- Menu screen ----------

function refreshMenu() {
  $('#menu-connected').textContent = `${manager.size} pod(s) connected`;
}

$('#btn-back-pods').onclick = () => show('pods');

$$('button[data-preset]').forEach((btn) => {
  btn.onclick = () => startPreset(btn.dataset.preset);
});

$('#btn-custom').onclick = () => show('config');

// ---------- Config screen ----------

const presetColors = [
  [255,255,255], [0,200,255], [255,50,50], [50,220,80],
  [255,200,0], [255,0,200], [180,100,255], [255,120,0],
];

function refreshConfig() {
  rebuildPlayers();
  refreshPodHelp();
  refreshEnabled();
}

function readPlayers() {
  return $$('#cfg-players-list .player-row').map((row, i) => ({
    name: `Player ${i + 1}`,
    colors: $$('input[type=color]', row).map(hexToRgb),
  }));
}

function rebuildPlayers() {
  const want = parseInt($('#cfg-players').value, 10) || 1;
  const list = $('#cfg-players-list');
  list.innerHTML = '';
  for (let i = 0; i < want; i++) {
    const row = document.createElement('div');
    row.className = 'player-row';
    const def = presetColors[i % presetColors.length];
    row.innerHTML = `
      <div class="player-label">Player ${i + 1}</div>
      <div class="colors-here"></div>
      <button class="secondary color-add">+</button>
      <button class="secondary color-rem">−</button>`;
    const ch = row.querySelector('.colors-here');
    ch.appendChild(makeColorInput(def));
    row.querySelector('.color-add').onclick = () => ch.appendChild(makeColorInput([255,255,255]));
    row.querySelector('.color-rem').onclick = () => {
      const inputs = $$('input[type=color]', ch);
      if (inputs.length > 1) inputs[inputs.length - 1].remove();
    };
    list.appendChild(row);
  }
}

function makeColorInput(rgb) {
  const inp = document.createElement('input');
  inp.type = 'color';
  inp.className = 'color-swatch';
  inp.value = rgbToHex(rgb);
  return inp;
}

function rgbToHex([r, g, b]) {
  return '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
}
function hexToRgb(input) {
  const v = (input.value || input).slice(1);
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}

function refreshPodHelp() {
  const stations = parseInt($('#cfg-stations').value, 10) || 1;
  const pps = parseInt($('#cfg-pps').value, 10) || 1;
  const need = stations * pps;
  const have = manager.size;
  const help = $('#cfg-pods-help');
  help.textContent = `(${need} pods needed; ${have} connected)`;
  help.className = 'help ' + (need <= have ? 'ok' : 'warn');
}

function selectedRadio(name) {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : null;
}

function refreshEnabled() {
  const lo = selectedRadio('lo');
  $('#cfg-timeout').disabled = !(lo === 'timeout' || lo === 'hit_and_timeout');
  const ld = selectedRadio('ld');
  $('#cfg-delay-fixed').disabled = ld !== 'fixed';
  $('#cfg-delay-min').disabled = ld !== 'random';
  $('#cfg-delay-max').disabled = ld !== 'random';
  const dm = selectedRadio('dm');
  $('#cfg-duration-time').disabled = !(dm === 'time' || dm === 'time_and_hit_count');
  $('#cfg-duration-hits').disabled = !(dm === 'hit_count' || dm === 'time_and_hit_count');
}

$('#cfg-stations').oninput = refreshPodHelp;
$('#cfg-pps').oninput = refreshPodHelp;
$('#cfg-players').onchange = rebuildPlayers;
['lo', 'ld', 'dm'].forEach((n) => {
  document.querySelectorAll(`input[name="${n}"]`).forEach((el) => el.onchange = refreshEnabled);
});

$('#btn-config-back').onclick = () => show('menu');

$('#btn-config-start').onclick = () => {
  const cfg = {
    stations: parseInt($('#cfg-stations').value, 10),
    podsPerStation: parseInt($('#cfg-pps').value, 10),
    players: readPlayers(),
    lightsOut: selectedRadio('lo'),
    timeoutS: parseFloat($('#cfg-timeout').value),
    lightDelay: selectedRadio('ld'),
    lightDelayFixedS: parseFloat($('#cfg-delay-fixed').value),
    lightDelayMinS: parseFloat($('#cfg-delay-min').value),
    lightDelayMaxS: parseFloat($('#cfg-delay-max').value),
    durationMode: selectedRadio('dm'),
    durationTimeS: parseFloat($('#cfg-duration-time').value),
    durationHitCount: parseInt($('#cfg-duration-hits').value, 10),
    cycles: parseInt($('#cfg-cycles').value, 10),
  };
  startCustom(cfg);
};

// ---------- Drills (presets) ----------

function presetConfig(kind) {
  const c = defaultConfig();
  c.podsPerStation = manager.size;
  switch (kind) {
    case 'random':
      c.lightsOut = LightsOut.HIT;
      c.lightDelay = LightDelay.NONE;
      c.durationMode = DurationMode.HIT_COUNT;
      c.durationHitCount = 10;
      c.players = [{ name: 'You', colors: [[255, 255, 255]] }];
      return { cfg: c, name: 'Random Light' };
    case 'sequence':
      c.lightsOut = LightsOut.HIT;
      c.lightDelay = LightDelay.NONE;
      c.durationMode = DurationMode.HIT_COUNT;
      c.durationHitCount = 8;
      c.players = [{ name: 'You', colors: [[0, 0, 255]] }];
      return { cfg: c, name: 'Sequence' };
    case 'color_match': {
      // Color match: distractors won't be implemented as a separate construct;
      // approximate as fast random-light with green.
      c.lightsOut = LightsOut.HIT_AND_TIMEOUT;
      c.timeoutS = 2.0;
      c.lightDelay = LightDelay.NONE;
      c.durationMode = DurationMode.HIT_COUNT;
      c.durationHitCount = 10;
      c.players = [{ name: 'You', colors: [[0, 255, 0]] }];
      return { cfg: c, name: 'Color Match' };
    }
  }
}

function startPreset(kind) {
  const { cfg, name } = presetConfig(kind);
  lastDrillKind = kind;
  startDrill(cfg, name);
}

function startCustom(cfg) {
  lastDrillKind = 'custom';
  lastDrillCfg = cfg;
  startDrill(cfg, 'Custom');
}

async function startDrill(cfg, displayName) {
  try {
    currentDrill = new CustomDrill(manager, cfg, { onUpdate: pollRunStats });
  } catch (e) {
    toast(`Cannot start: ${e.message}`, 'error');
    return;
  }
  $('#run-name').textContent = displayName;
  $('#run-hits').textContent = '0';
  $('#run-misses').textContent = '0';
  $('#run-last').textContent = 'Tap pods as they light up.';
  show('run');
  await requestWakeLock();
  pollTimer = setInterval(pollRunStats, 100);
  try {
    const stats = await currentDrill.run();
    stats.drillName = displayName;
    showResults(stats);
  } catch (e) {
    toast(`Drill error: ${e.message}`, 'error');
    show('menu');
  } finally {
    clearInterval(pollTimer); pollTimer = null;
    releaseWakeLock();
  }
}

function pollRunStats() {
  if (!currentDrill) return;
  let hits = 0, misses = 0, lastRt = null;
  for (const st of currentDrill.stations) {
    hits += st.stats.hits;
    misses += st.stats.misses;
    if (st.stats.reactionTimesMs.length) {
      lastRt = st.stats.reactionTimesMs[st.stats.reactionTimesMs.length - 1];
    }
  }
  $('#run-hits').textContent = hits;
  $('#run-misses').textContent = misses;
  if (lastRt != null) $('#run-last').textContent = `Last reaction: ${lastRt} ms`;
}

$('#btn-abort').onclick = () => {
  if (currentDrill) currentDrill.abort();
};

// ---------- Results ----------

function showResults(stats) {
  const summary = statsSummary(stats);
  $('#results-title').textContent = stats.drillName;
  if (stats.reactionTimesMs.length > 0) {
    $('#results-big').textContent = Math.round(summary.meanMs);
    $('#results-caption').textContent = 'ms — mean reaction time';
  } else {
    $('#results-big').textContent = '—';
    $('#results-caption').textContent = 'no successful taps';
  }
  const parts = [
    `<b>Hits:</b> ${stats.hits}  &nbsp; <b>Misses:</b> ${stats.misses}  &nbsp; <b>Accuracy:</b> ${Math.round(summary.accuracy * 100)}%`,
  ];
  if (stats.reactionTimesMs.length) {
    parts.push(`<b>Best:</b> ${summary.bestMs} ms &nbsp; <b>Median:</b> ${Math.round(summary.medianMs)} ms &nbsp; <b>Worst:</b> ${summary.worstMs} ms`);
  }
  if (stats.totalTimeMs) {
    parts.push(`<b>Total time:</b> ${(stats.totalTimeMs / 1000).toFixed(1)}s`);
  }
  if (Object.keys(stats.subscores).length) {
    parts.push('<br><b>Per-station:</b>');
    for (const [label, sub] of Object.entries(stats.subscores)) {
      const sub2 = statsSummary(sub);
      let line = `&nbsp;&nbsp;${escapeHtml(label)}: hits=${sub.hits} misses=${sub.misses} acc=${Math.round(sub2.accuracy * 100)}%`;
      if (sub.reactionTimesMs.length) line += ` mean=${Math.round(sub2.meanMs)}ms best=${sub2.bestMs}ms`;
      parts.push(line);
    }
  }
  $('#results-detail').innerHTML = parts.join('<br>');
  show('results');
}

$('#btn-results-menu').onclick = () => show('menu');
$('#btn-results-again').onclick = () => {
  if (lastDrillKind === 'custom' && lastDrillCfg) startCustom(lastDrillCfg);
  else if (lastDrillKind) startPreset(lastDrillKind);
};

// ---------- Wake lock (keep screen on during drills) ----------

async function requestWakeLock() {
  try {
    if (navigator.wakeLock) wakeLock = await navigator.wakeLock.request('screen');
  } catch {}
}
function releaseWakeLock() {
  if (wakeLock) { try { wakeLock.release(); } catch {} wakeLock = null; }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && currentDrill && !wakeLock) requestWakeLock();
});

// ---------- Misc ----------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Initial render
refreshPodList();

// Service worker (best-effort; silently fails on file://)
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

// Bluefy / Web Bluetooth availability hint
if (!navigator.bluetooth) {
  toast('Web Bluetooth not available. On iPhone, open this page in the Bluefy browser (App Store).', 'warn');
}
