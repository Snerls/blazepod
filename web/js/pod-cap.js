// Native (iOS / Capacitor) implementation of Pod / pickPod.
// Uses @capacitor-community/bluetooth-le, which talks to CoreBluetooth on iOS
// and gets full manufacturerData access — the thing iOS Web Bluetooth strips.

import { BleClient } from '@capacitor-community/bluetooth-le';

import {
  AUTH_PREFIX, COLOR_CHAR_UUID, COLOR_OFF, COLOR_SERVICE_UUID,
  TAP_CHAR_UUID, TAP_SERVICE_UUID, UART_RX_CHAR_UUID, UART_SERVICE_UUID,
  buildAuthPayload, decodeTap, encodeColor, toUint8Array,
} from './protocol.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let _initialized = false;
async function ensureInit() {
  if (_initialized) return;
  await BleClient.initialize({ androidNeverForLocation: true });
  _initialized = true;
}

function dataViewFromBytes(bytes) {
  const u = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return new DataView(u.buffer, u.byteOffset, u.byteLength);
}

function bytesFromDataView(dv) {
  return new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
}

// ----- mfr-data cache (still useful: skip repeat scans) ----------------------
const MFR_CACHE_KEY = 'blazepod.mfr.v1';
export const mfrCache = {
  _read() { try { return JSON.parse(localStorage.getItem(MFR_CACHE_KEY) || '{}') || {}; } catch { return {}; } },
  _write(o) { try { localStorage.setItem(MFR_CACHE_KEY, JSON.stringify(o)); } catch {} },
  get(id) { const h = this._read()[id]; if (!h) return null;
    const a = new Uint8Array(h.length / 2); for (let i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i*2,2), 16); return a; },
  set(id, b) { const o = this._read(); o[id] = Array.from(b, (x) => x.toString(16).padStart(2,'0')).join(''); this._write(o); },
  forget(id) { const o = this._read(); if (id in o) { delete o[id]; this._write(o); } },
  clear() { this._write({}); },
};

// ----- Pick one pod via a brief LE scan + on-screen list ---------------------

const PICKER_SCAN_MS = 6000;

// Cache of recently-seen mfr per device id, populated by the scan listener.
// Per-pod mfr rotates over time so we always re-scan immediately before connect.
const _recentMfr = new Map(); // deviceId -> { bytes, capturedAt }

let _scanRunning = false;

async function scanForPods({ ms = PICKER_SCAN_MS, onFound } = {}) {
  await ensureInit();
  if (_scanRunning) {
    try { await BleClient.stopLEScan(); } catch {}
  }
  _scanRunning = true;
  const seen = new Map(); // deviceId -> { device, mfr }
  await BleClient.requestLEScan({ namePrefix: 'BlazePod', allowDuplicates: true }, (result) => {
    // result: { device: { deviceId, name }, manufacturerData?: { [companyId]: DataView }, ... }
    const id = result.device.deviceId;
    let mfr = null;
    if (result.manufacturerData) {
      for (const [, dv] of Object.entries(result.manufacturerData)) {
        const b = bytesFromDataView(dv);
        if (b.length >= 5 && (mfr === null || b.length > mfr.length)) mfr = b;
      }
    }
    if (mfr) {
      _recentMfr.set(id, { bytes: mfr, capturedAt: Date.now() });
      const prev = seen.get(id);
      if (!prev || mfr.length > prev.mfr.length) {
        seen.set(id, { device: result.device, mfr });
        if (onFound) try { onFound({ id, name: result.device.name || 'BlazePod', mfr }); } catch {}
      }
    } else if (!seen.has(id)) {
      seen.set(id, { device: result.device, mfr: null });
      if (onFound) try { onFound({ id, name: result.device.name || 'BlazePod', mfr: null }); } catch {}
    }
  });
  await sleep(ms);
  try { await BleClient.stopLEScan(); } catch {}
  _scanRunning = false;
  return Array.from(seen.values());
}

// Show a simple modal listing pods with captured mfr data; resolve with the
// chosen one. ui.js can later replace this with its own modal — this one is
// self-contained so pickPod() works out-of-the-box.
async function chooseFromList(items) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';
    const box = document.createElement('div');
    box.style.cssText = 'background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px;max-width:520px;width:100%;color:#e6e6e6;font-family:-apple-system,sans-serif;max-height:80vh;display:flex;flex-direction:column;gap:8px;';
    const title = document.createElement('div');
    title.textContent = 'Pick a pod to add';
    title.style.cssText = 'font-size:18px;font-weight:700;margin-bottom:4px;';
    box.appendChild(title);
    const sub = document.createElement('div');
    sub.textContent = 'Tap a pod to connect it. Cancel to stop adding.';
    sub.style.cssText = 'font-size:13px;color:#8b949e;margin-bottom:8px;';
    box.appendChild(sub);
    const list = document.createElement('div');
    list.style.cssText = 'overflow-y:auto;display:flex;flex-direction:column;gap:6px;';
    box.appendChild(list);
    if (items.length === 0) {
      const empty = document.createElement('div');
      empty.textContent = 'No pods found. Tap any pod to wake it, then try again.';
      empty.style.cssText = 'color:#f85149;padding:8px;';
      list.appendChild(empty);
    } else {
      for (const it of items) {
        const btn = document.createElement('button');
        btn.style.cssText = 'background:#0a0c10;border:1px solid #30363d;border-radius:8px;padding:12px;color:#e6e6e6;text-align:left;font:inherit;cursor:pointer;';
        const mfrText = it.mfr ? `mfr=${Array.from(it.mfr,(b)=>b.toString(16).padStart(2,'0')).join('')}` : '<i>no mfr (skip)</i>';
        btn.innerHTML = `<div style="font-weight:600">${it.device.name || 'BlazePod'}</div>
                          <div style="font-size:11px;color:#8b949e;font-family:ui-monospace,Menlo,monospace">${it.device.deviceId}</div>
                          <div style="font-size:11px;color:#8b949e;font-family:ui-monospace,Menlo,monospace">${mfrText}</div>`;
        btn.onclick = () => { document.body.removeChild(overlay); resolve(it); };
        if (!it.mfr) btn.disabled = true;
        list.appendChild(btn);
      }
    }
    const cancel = document.createElement('button');
    cancel.textContent = 'Cancel';
    cancel.style.cssText = 'background:#30363d;border:0;border-radius:8px;padding:12px;color:#fff;font:inherit;font-weight:600;cursor:pointer;margin-top:8px;';
    cancel.onclick = () => { document.body.removeChild(overlay); resolve(null); };
    box.appendChild(cancel);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  });
}

export async function pickPod() {
  const items = await scanForPods({ ms: PICKER_SCAN_MS });
  // Filter out items we've already added (caller decides)
  const choice = await chooseFromList(items);
  if (!choice) {
    const e = new Error('user cancelled picker');
    e.name = 'NotFoundError';
    throw e;
  }
  return wrapAsBluetoothDevice(choice.device, choice.mfr);
}

// Wrap a Capacitor BleDevice + captured mfr into a "device" object that
// quacks enough like Web Bluetooth's BluetoothDevice for the rest of the
// app to use uniformly.
function wrapAsBluetoothDevice(bleDevice, mfrBytes) {
  const listeners = { gattserverdisconnected: new Set() };
  return {
    id: bleDevice.deviceId,
    name: bleDevice.name || 'BlazePod',
    _cachedMfr: mfrBytes,
    _capacitor: true,
    addEventListener(name, cb) { (listeners[name] = listeners[name] || new Set()).add(cb); },
    removeEventListener(name, cb) { listeners[name]?.delete(cb); },
    _emit(name) { for (const cb of (listeners[name] || [])) try { cb(); } catch {} },
  };
}

// ----- The Pod class --------------------------------------------------------

export class Pod {
  constructor(device) {
    this.device = device;
    this.address = device.id;
    this.name = device.name || '?';
    this.mfrData = device._cachedMfr || mfrCache.get(device.id) || null;
    this._listeners = new Set();
    this._connected = false;
    this._tapHandler = (rawData) => this._onTap(rawData);
  }

  get isConnected() { return this._connected; }
  onTap(cb) { this._listeners.add(cb); return () => this._listeners.delete(cb); }
  clearTapListeners() { this._listeners.clear(); }

  async connect({ retries = 2 } = {}) {
    let lastErr;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        if (attempt > 0) await sleep(500);
        await this._connectOnce();
        return;
      } catch (e) {
        lastErr = e;
        try { await BleClient.disconnect(this.address); } catch {}
      }
    }
    throw lastErr;
  }

  async _connectOnce() {
    await ensureInit();

    // Refresh mfrData if stale (>30s) — pods rotate it frequently
    const recent = _recentMfr.get(this.address);
    const ageMs = recent ? Date.now() - recent.capturedAt : Infinity;
    if (!recent || ageMs > 30000) {
      const fresh = await captureMfrFor(this.address, 5000);
      if (fresh) this.mfrData = fresh;
    } else {
      this.mfrData = recent.bytes;
    }
    if (!this.mfrData) {
      throw new Error('could not capture manufacturerData — wake the pod and try again');
    }
    mfrCache.set(this.address, this.mfrData);

    await BleClient.connect(this.address, () => {
      this._connected = false;
      this.device._emit?.('gattserverdisconnected');
    });

    const auth = buildAuthPayload(this.mfrData);
    await BleClient.write(this.address, UART_SERVICE_UUID, UART_RX_CHAR_UUID, dataViewFromBytes(auth));

    await BleClient.startNotifications(
      this.address, TAP_SERVICE_UUID, TAP_CHAR_UUID, this._tapHandler,
    );

    this._connected = true;
  }

  async setColor(r, g, b, { offOnTap = false } = {}) {
    const data = encodeColor(r, g, b, { offOnTap });
    await BleClient.writeWithoutResponse(
      this.address, COLOR_SERVICE_UUID, COLOR_CHAR_UUID, dataViewFromBytes(data),
    );
  }

  async turnOff() { await this.setColor(0, 0, 0); }

  async flash(r = 255, g = 0, b = 0, { count = 3, onMs = 250, offMs = 200 } = {}) {
    for (let i = 0; i < count; i++) {
      await this.setColor(r, g, b);
      await sleep(onMs);
      await this.turnOff();
      if (i < count - 1) await sleep(offMs);
    }
  }

  async disconnect() {
    if (this._connected) {
      try { await BleClient.stopNotifications(this.address, TAP_SERVICE_UUID, TAP_CHAR_UUID); } catch {}
      try { await BleClient.disconnect(this.address); } catch {}
    }
    this._connected = false;
  }

  _onTap(rawData) {
    let ev;
    try { ev = decodeTap(bytesFromDataView(rawData)); }
    catch (e) { console.warn('bad tap payload', e); return; }
    for (const cb of this._listeners) {
      try { cb(this, ev); } catch (err) { console.warn('tap listener threw', err); }
    }
  }
}

// Quick targeted re-scan to refresh mfrData for one device id.
async function captureMfrFor(deviceId, ms) {
  await ensureInit();
  if (_scanRunning) {
    try { await BleClient.stopLEScan(); } catch {}
  }
  _scanRunning = true;
  let mfr = null;
  await BleClient.requestLEScan({ namePrefix: 'BlazePod', allowDuplicates: true }, (result) => {
    if (result.device.deviceId !== deviceId) return;
    if (result.manufacturerData) {
      for (const [, dv] of Object.entries(result.manufacturerData)) {
        const b = bytesFromDataView(dv);
        if (b.length >= 5 && (mfr === null || b.length > mfr.length)) {
          mfr = b;
          _recentMfr.set(deviceId, { bytes: b, capturedAt: Date.now() });
        }
      }
    }
  });
  // Wait until we see one or run out of time
  const start = Date.now();
  while (!mfr && Date.now() - start < ms) await sleep(100);
  try { await BleClient.stopLEScan(); } catch {}
  _scanRunning = false;
  return mfr;
}
