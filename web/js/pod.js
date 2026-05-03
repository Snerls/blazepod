// Pod runtime dispatcher.
//
// Two implementations live alongside this file:
//   - ./pod-cap.js  →  Capacitor native (iOS) — uses CoreBluetooth via the
//                       Capacitor BLE plugin. Has full manufacturerData
//                       access. This is what the iOS app uses.
//   - ./pod-web.js  →  Web Bluetooth — used in Chrome desktop / Android Chrome
//                       and the Node test runner. Does NOT work on iOS
//                       Safari/Bluefy because Apple's WebKit strips
//                       manufacturerData.
//
// The right impl is selected at module-init time by checking
// `window.Capacitor.isNativePlatform()`.

const _onCapacitor = typeof globalThis !== 'undefined'
  && globalThis.window
  && globalThis.window.Capacitor
  && typeof globalThis.window.Capacitor.isNativePlatform === 'function'
  && globalThis.window.Capacitor.isNativePlatform();

const impl = _onCapacitor
  ? await import('./pod-cap.js')
  : await import('./pod-web.js');

export const Pod = impl.Pod;
export const pickPod = impl.pickPod;
export const mfrCache = impl.mfrCache;
