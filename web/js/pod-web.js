// Web Bluetooth implementation of Pod / pickPod / mfrCache.
// Used in Chrome desktop, Chrome Android, etc. NOT used in iOS Bluefy
// (see pod.js dispatcher: iOS uses the Capacitor native impl instead).

import {
  AUTH_PREFIX, COLOR_CHAR_UUID, COLOR_OFF, COLOR_SERVICE_UUID,
  TAP_CHAR_UUID, TAP_SERVICE_UUID, UART_RX_CHAR_UUID, UART_SERVICE_UUID,
  buildAuthPayload, bytesToHex, decodeTap, encodeColor, hexToBytes, toUint8Array,
} from './protocol.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function pickMfrDataFromAdvertisement(event) {
  if (!event.manufacturerData || event.manufacturerData.size === 0) return null;
  let best = null;
  event.manufacturerData.forEach((dv) => {
    const bytes = toUint8Array(dv);
    if (bytes.length >= 5 && (best === null || bytes.length > best.length)) {
      best = bytes;
    }
  });
  return best;
}

async function awaitMfrData(device, { timeoutMs = 10000, onWaiting } = {}) {
  if (!device.watchAdvertisements) {
    throw new Error("Browser doesn't expose advertisement data — iOS Web Bluetooth is not supported. Use the native iOS app, or Chrome on desktop/Android.");
  }
  const cached = device._cachedMfr;
  if (cached) return cached;
  return new Promise(async (resolve, reject) => {
    let done = false;
    const onAd = (ev) => {
      const mfr = pickMfrDataFromAdvertisement(ev);
      if (mfr && !done) {
        done = true;
        device.removeEventListener('advertisementreceived', onAd);
        device._cachedMfr = mfr;
        resolve(mfr);
      }
    };
    device.addEventListener('advertisementreceived', onAd);
    try { await device.watchAdvertisements(); }
    catch (e) { device.removeEventListener('advertisementreceived', onAd); return reject(e); }
    if (onWaiting) { try { onWaiting(); } catch {} }
    setTimeout(() => {
      if (!done) {
        device.removeEventListener('advertisementreceived', onAd);
        reject(new Error(`pod didn't broadcast within ${Math.round(timeoutMs / 1000)}s — tap the pod hard, then try again`));
      }
    }, timeoutMs);
  });
}

const MFR_CACHE_KEY = 'blazepod.mfr.v1';
export const mfrCache = {
  _read() { try { return JSON.parse(localStorage.getItem(MFR_CACHE_KEY) || '{}') || {}; } catch { return {}; } },
  _write(obj) { try { localStorage.setItem(MFR_CACHE_KEY, JSON.stringify(obj)); } catch {} },
  get(deviceId) { const hex = this._read()[deviceId]; return hex ? hexToBytes(hex) : null; },
  set(deviceId, bytes) { const obj = this._read(); obj[deviceId] = bytesToHex(bytes); this._write(obj); },
  forget(deviceId) { const obj = this._read(); if (deviceId in obj) { delete obj[deviceId]; this._write(obj); } },
  clear() { this._write({}); },
};

export class Pod {
  constructor(device) {
    this.device = device;
    this.address = device.id;
    this.name = device.name || '?';
    this.mfrData = null;
    this.server = null;
    this._tapChar = null;
    this._listeners = new Set();
    this._connected = false;
    this._notifyHandler = (event) => this._onNotify(event);
    device.addEventListener('gattserverdisconnected', () => { this._connected = false; });
  }

  get isConnected() { return this._connected && this.server?.connected === true; }
  onTap(cb) { this._listeners.add(cb); return () => this._listeners.delete(cb); }
  clearTapListeners() { this._listeners.clear(); }

  async connect({ retries = 2, onWaiting } = {}) {
    let lastErr;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        if (attempt > 0) await sleep(500);
        await this._connectOnce({ onWaiting });
        return;
      } catch (e) {
        lastErr = e;
        try { this.device.gatt?.disconnect(); } catch {}
      }
    }
    throw lastErr;
  }

  async _connectOnce({ onWaiting } = {}) {
    this.mfrData = await awaitMfrData(this.device, { onWaiting });
    this.server = await this.device.gatt.connect();

    const uart = await this.server.getPrimaryService(UART_SERVICE_UUID);
    const rxChar = await uart.getCharacteristic(UART_RX_CHAR_UUID);
    if (rxChar.writeValueWithResponse) {
      await rxChar.writeValueWithResponse(buildAuthPayload(this.mfrData));
    } else {
      await rxChar.writeValue(buildAuthPayload(this.mfrData));
    }

    const tap = await this.server.getPrimaryService(TAP_SERVICE_UUID);
    this._tapChar = await tap.getCharacteristic(TAP_CHAR_UUID);
    this._tapChar.addEventListener('characteristicvaluechanged', this._notifyHandler);
    await this._tapChar.startNotifications();

    const colorService = await this.server.getPrimaryService(COLOR_SERVICE_UUID);
    this._colorChar = await colorService.getCharacteristic(COLOR_CHAR_UUID);

    this._connected = true;
  }

  async setColor(r, g, b, { offOnTap = false } = {}) {
    if (!this._colorChar) throw new Error('not connected');
    const data = encodeColor(r, g, b, { offOnTap });
    if (this._colorChar.writeValueWithoutResponse) {
      await this._colorChar.writeValueWithoutResponse(data);
    } else {
      await this._colorChar.writeValue(data);
    }
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
    if (this._tapChar) {
      try { await this._tapChar.stopNotifications(); } catch {}
      this._tapChar.removeEventListener('characteristicvaluechanged', this._notifyHandler);
    }
    if (this.server?.connected) {
      try { this.device.gatt.disconnect(); } catch {}
    }
    this._connected = false;
  }

  _onNotify(event) {
    let ev;
    try { ev = decodeTap(event.target.value); }
    catch (e) { console.warn('bad tap payload from', this.address, e); return; }
    for (const cb of this._listeners) {
      try { cb(this, ev); } catch (err) { console.warn('tap listener threw', err); }
    }
  }
}

export async function pickPod() {
  if (!navigator.bluetooth) {
    throw new Error("This browser doesn't support Web Bluetooth. On iOS, use the BlazePod native app.");
  }
  return navigator.bluetooth.requestDevice({
    filters: [{ namePrefix: 'BlazePod' }],
    optionalServices: [UART_SERVICE_UUID, COLOR_SERVICE_UUID, TAP_SERVICE_UUID],
  });
}
