// BlazePod BLE wire protocol — JS port of src/blazepod/protocol.py.
// Reverse-engineered from https://github.com/sasodoma/blazepod-hacking.

export const UART_SERVICE_UUID  = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
export const UART_RX_CHAR_UUID  = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
export const COLOR_SERVICE_UUID = '50c97bfa-4cb8-4c84-b745-0e58a0280cd6';
export const COLOR_CHAR_UUID    = '50c912a2-4cb8-4c84-b745-0e58a0280cd6';
export const TAP_SERVICE_UUID   = '50c928bd-4cb8-4c84-b745-0e58a0280cd6';
export const TAP_CHAR_UUID      = '50c9727e-4cb8-4c84-b745-0e58a0280cd6';

export const AUTH_PREFIX = new Uint8Array([0x73, 0x65, 0x61]); // "sea"

export const TAP_STATE = Object.freeze({
  OFF:      0x00,
  LIT_STAY: 0x21,
  LIT_OFF:  0x25,
});

// JS bitwise ops are 32-bit signed; `>>> 0` coerces to uint32.
// `(a + b) >>> 0` gives `(a + b) mod 2^32` — what we need for the C uint32 wrap.
export function computeAuthSuffix(mfrData) {
  const bytes = toUint8Array(mfrData);
  if (bytes.length < 5) {
    throw new Error(`manufacturer data too short: ${bytes.length} bytes, need >= 5`);
  }
  const tail = bytes.slice(-5);
  const offset = tail[0];
  const byteArray = tail.slice(1); // 4 bytes

  const poly = (0xEDB88321 + (offset % 50)) >>> 0;

  let crc = 0xFFFFFFFF;
  for (const b of byteArray) {
    crc = (crc ^ b) >>> 0;
    for (let i = 0; i < 8; i++) {
      if (crc & 1) {
        crc = ((crc >>> 1) ^ poly) >>> 0;
      } else {
        crc = (crc >>> 1) >>> 0;
      }
    }
  }

  crc = (crc ^ 0xFFFFFFFF) >>> 0;
  crc = (crc + ((crc << 3) >>> 0)) >>> 0;
  crc = (crc ^ (crc >>> 11)) >>> 0;
  crc = (crc + ((crc << 15) >>> 0)) >>> 0;

  return new Uint8Array([
    crc & 0xFF,
    (crc >>> 8) & 0xFF,
    (crc >>> 16) & 0xFF,
    (crc >>> 24) & 0xFF,
  ]);
}

export function buildAuthPayload(mfrData) {
  const suffix = computeAuthSuffix(mfrData);
  const out = new Uint8Array(7);
  out.set(AUTH_PREFIX, 0);
  out.set(suffix, 3);
  return out;
}

// Color is encoded as G B R (NOT RGB). Optional 4th byte 0x01 = pod auto-extinguishes when tapped.
export function encodeColor(r, g, b, { offOnTap = false } = {}) {
  for (const [name, v] of [['r', r], ['g', g], ['b', b]]) {
    if (!Number.isInteger(v) || v < 0 || v > 255) {
      throw new Error(`${name} out of range 0..255: ${v}`);
    }
  }
  return offOnTap
    ? new Uint8Array([g, b, r, 0x01])
    : new Uint8Array([g, b, r]);
}

export const COLOR_OFF = encodeColor(0, 0, 0);

// Tap notification: 8 bytes; [state, ms_le_u32(4), unknown(3)]
export function decodeTap(payload) {
  const bytes = toUint8Array(payload);
  if (bytes.length < 5) {
    throw new Error(`tap payload too short: ${bytes.length} bytes`);
  }
  const stateByte = bytes[0];
  if (stateByte !== TAP_STATE.OFF && stateByte !== TAP_STATE.LIT_STAY && stateByte !== TAP_STATE.LIT_OFF) {
    throw new Error(`unknown tap state byte 0x${stateByte.toString(16).padStart(2, '0').toUpperCase()}`);
  }
  const elapsedMs = (bytes[1]) | (bytes[2] << 8) | (bytes[3] << 16) | (bytes[4] << 24);
  return {
    state: stateByte,
    elapsedMs: elapsedMs >>> 0,
    raw: bytes,
    hitLitPod: stateByte === TAP_STATE.LIT_STAY || stateByte === TAP_STATE.LIT_OFF,
  };
}

// Accept Uint8Array, Array, ArrayBuffer, or DataView.
export function toUint8Array(x) {
  if (x instanceof Uint8Array) return x;
  if (x instanceof DataView) return new Uint8Array(x.buffer, x.byteOffset, x.byteLength);
  if (x instanceof ArrayBuffer) return new Uint8Array(x);
  if (Array.isArray(x)) return new Uint8Array(x);
  throw new Error('unsupported byte source: ' + Object.prototype.toString.call(x));
}

export function bytesToHex(bytes) {
  return Array.from(toUint8Array(bytes), (b) => b.toString(16).padStart(2, '0').toUpperCase()).join('');
}

export function hexToBytes(hex) {
  const clean = hex.replace(/[^0-9a-fA-F]/g, '');
  if (clean.length % 2) throw new Error('hex string odd length');
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
  return out;
}
