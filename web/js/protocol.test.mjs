// Cross-check the JS protocol port against the Python `tests/test_protocol.py`.
// Run with: node web/js/protocol.test.mjs

import {
  AUTH_PREFIX, buildAuthPayload, computeAuthSuffix, decodeTap,
  encodeColor, COLOR_OFF, TAP_STATE, bytesToHex, hexToBytes,
} from './protocol.js';

let passed = 0, failed = 0;
function eq(name, actual, expected) {
  const a = actual instanceof Uint8Array ? bytesToHex(actual) : String(actual);
  const e = expected instanceof Uint8Array ? bytesToHex(expected) : String(expected);
  if (a === e) { passed++; console.log(`  PASS  ${name}`); }
  else { failed++; console.log(`  FAIL  ${name}\n        got      ${a}\n        expected ${e}`); }
}

// Independent C-port copy used by the Python test as the reference.
const U32 = 0xFFFFFFFF;
function referenceCPort(offset, byteArray) {
  const poly = (0xEDB88321 + (offset % 50)) >>> 0;
  let crc = 0xFFFFFFFF;
  for (const b of byteArray) {
    crc = (crc ^ b) >>> 0;
    for (let i = 0; i < 8; i++) {
      crc = (crc & 1) ? ((crc >>> 1) ^ poly) >>> 0 : (crc >>> 1) >>> 0;
    }
  }
  crc = (crc ^ 0xFFFFFFFF) >>> 0;
  crc = (crc + ((crc << 3) >>> 0)) >>> 0;
  crc = (crc ^ (crc >>> 11)) >>> 0;
  crc = (crc + ((crc << 15) >>> 0)) >>> 0;
  return new Uint8Array([0x73, 0x65, 0x61,
    crc & 0xFF, (crc >>> 8) & 0xFF, (crc >>> 16) & 0xFF, (crc >>> 24) & 0xFF]);
}

const README_EXAMPLE = hexToBytes('5A01DEADBEEF');

// --- Auth tests ---
eq('AUTH_PREFIX is "sea"', AUTH_PREFIX, new Uint8Array([0x73, 0x65, 0x61]));
eq('payload starts with sea', buildAuthPayload(README_EXAMPLE).slice(0, 3), new Uint8Array([0x73, 0x65, 0x61]));
eq('payload length 7', String(buildAuthPayload(README_EXAMPLE).length), '7');

eq(
  'matches independent C port (offset=1, DEADBEEF)',
  buildAuthPayload(README_EXAMPLE),
  referenceCPort(0x01, [0xDE, 0xAD, 0xBE, 0xEF]),
);

eq(
  'leading bytes ignored',
  computeAuthSuffix(README_EXAMPLE),
  computeAuthSuffix(hexToBytes('00AABB' + '5A01DEADBEEF')),
);

eq(
  'different offset → different suffix',
  bytesToHex(computeAuthSuffix(new Uint8Array([0x01, 0xDE, 0xAD, 0xBE, 0xEF])))
    !== bytesToHex(computeAuthSuffix(new Uint8Array([0x02, 0xDE, 0xAD, 0xBE, 0xEF]))),
  'true',
);

for (const offset of [0, 1, 25, 49, 50, 99, 200, 255]) {
  const body = new Uint8Array([0x12, 0x34, 0x56, 0x78]);
  const expected = referenceCPort(offset, body);
  const actual = buildAuthPayload(new Uint8Array([offset, ...body]));
  eq(`matches C port across offsets (offset=${offset})`, actual, expected);
}

// --- Color tests ---
eq('encode red → G B R', encodeColor(255, 0, 0), new Uint8Array([0, 0, 0xFF]));
eq('encode green → G B R', encodeColor(0, 255, 0), new Uint8Array([0xFF, 0, 0]));
eq('encode blue → G B R', encodeColor(0, 0, 255), new Uint8Array([0, 0xFF, 0]));
eq('off-on-tap appends 0x01', encodeColor(10, 20, 30, { offOnTap: true }), new Uint8Array([20, 30, 10, 0x01]));
eq('COLOR_OFF', COLOR_OFF, new Uint8Array([0, 0, 0]));

// --- Tap tests ---
{
  const ev = decodeTap(hexToBytes('25A861000000000000').slice(0, 8));
  eq('decode lit_off state', String(ev.state), String(TAP_STATE.LIT_OFF));
  eq('decode lit_off elapsed_ms = 0x61A8', String(ev.elapsedMs), String(0x61A8));
  eq('decode lit_off hitLitPod', String(ev.hitLitPod), 'true');
}
{
  const ev = decodeTap(new Uint8Array([0x21, 0xE8, 0x03, 0, 0, 0, 0, 0]));
  eq('decode lit_stay state', String(ev.state), String(TAP_STATE.LIT_STAY));
  eq('decode lit_stay elapsed_ms = 1000', String(ev.elapsedMs), '1000');
}
{
  const ev = decodeTap(new Uint8Array(8));
  eq('decode off state', String(ev.state), String(TAP_STATE.OFF));
  eq('decode off elapsed_ms = 0', String(ev.elapsedMs), '0');
  eq('decode off hitLitPod', String(ev.hitLitPod), 'false');
}

// --- Error cases ---
try { computeAuthSuffix(new Uint8Array([0, 1, 2, 3])); failed++; console.log('  FAIL  short mfr should throw'); }
catch { passed++; console.log('  PASS  short mfr throws'); }

try { decodeTap(new Uint8Array([0xFF, 0, 0, 0, 0, 0, 0, 0])); failed++; console.log('  FAIL  unknown tap state should throw'); }
catch { passed++; console.log('  PASS  unknown tap state throws'); }

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
