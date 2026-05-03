# BlazePod web controller (iPhone-only, no PC needed)

Static web app that runs the same drills as the Python desktop app, but inside a browser on your iPhone.

## Why Bluefy?

Apple Safari doesn't support Web Bluetooth. The free third-party browser **[Bluefy](https://apps.apple.com/us/app/bluefy-web-ble-browser/id1492822055)** does. Install it once from the App Store; that's the only setup. No developer account, no sideloading, no laptop.

## How to use

1. Install **Bluefy – Web BLE Browser** from the App Store on your iPhone.
2. Host this `web/` folder somewhere reachable over HTTPS — the easiest path is GitHub Pages (free).
3. Open the URL in **Bluefy** (not Safari).
4. Tap **+ Add pod** → pick a BlazePod from the iOS picker → it flashes green when connected. Repeat for each pod.
5. Tap **Continue →** → pick a drill (or **Custom drill…** for the full configuration) → start.

## Local development

You can serve `web/` over HTTPS on your laptop (Web Bluetooth requires HTTPS or localhost) for desktop testing in Chrome:

```powershell
# from the project root, with Python:
python -m http.server 8000 --directory web
# then open http://localhost:8000 in Chrome (NOT Safari)
```

For protocol-only tests with no hardware, open `web/test.html` in any browser — should print all PASS.

To run the same test suite under node:

```powershell
node web/js/protocol.test.mjs
```

## File layout

```
web/
  index.html              # single page, mobile-first
  styles.css
  manifest.json           # PWA manifest
  sw.js                   # service worker — works offline once cached
  test.html               # in-browser CRC + codec tests
  js/
    protocol.js           # UUIDs, auth CRC, color/tap codecs (mirrors src/blazepod/protocol.py)
    pod.js                # one BluetoothDevice + GATT handshake
    manager.js            # multi-pod orchestration + tap dispatch
    drill.js              # CustomDrill engine + presets
    ui.js                 # screen routing + form state
    protocol.test.mjs     # node test runner
```

## Caveats

- **Bluefy must stay foregrounded.** iOS suspends background JS. We request a screen wake-lock during drills so the screen doesn't sleep.
- **iPhone BLE concurrency limits.** Newer iPhones handle 6+ pods; older ones may cap at 4–5.
- **Internet only needed for first load.** After the service worker caches everything (one visit while online), the app runs offline at the gym.
