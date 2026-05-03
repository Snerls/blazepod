# Project context for Claude

Subscription-free BlazePod controller. Two parallel codebases sharing only the
BLE protocol semantics:

- **`src/blazepod/`** — Python desktop app (Bleak + PyQt6). Runs on Windows/Mac/Linux.
- **`web/`** — Web Bluetooth web app served from Vercel, used in the **Bluefy**
  browser on iPhone (Safari does not support Web Bluetooth on iOS).

Hosted at `https://web-psi-silk-uz4uykpau7.vercel.app`. Push to `main` (or run
`vercel --prod` from `web/`) to redeploy.

## Live BLE testing

This machine has a working BLE adapter and the user keeps the BlazePods nearby
during sessions. **You can drive the user's hardware live** by running Python +
Bleak scripts from Bash. Use this to validate protocol-level changes — the
roundtrip is faster and more reliable than asking the user to test on the phone.

When you make a change that could break BLE behavior or invalidate an
assumption, proactively run the relevant test from `tests/live_ble_tests.py`:

| Trigger | Test to run |
|---|---|
| Touched `protocol.py` (auth CRC, codecs) | `python tests/live_ble_tests.py auth` |
| Changed mfrData caching / `getDevices` flow / anything assuming mfrData is stable | `python tests/live_ble_tests.py stability` |
| Changed connect retry logic, timeouts, or `BleakClient` lifecycle | `python tests/live_ble_tests.py warm` |
| Changed concurrent-connect logic, `connect_all`, parallel pod handling | `python tests/live_ble_tests.py stress` |
| Major rework — anything BLE-adjacent | `python tests/live_ble_tests.py all` |

If a test fails, the change is broken. Don't ship it.

## What you CANNOT test

The iPhone / Bluefy / Web Bluetooth path runs on the user's phone in a browser
you can't see. Anything that's specific to:

- iOS CoreBluetooth quirks
- Web Bluetooth API differences (`watchAdvertisements`, `requestDevice`,
  `getDevices`)
- Bluefy-specific behavior or bugs
- Service worker caching on iOS

…must be tested by the user. When you ship a web-app change, tell them
explicitly what to verify on the phone (the toast / global error handler
in `web/js/ui.js` makes silent failures visible).

## Working style preferences

The user is action-oriented and wants terse responses. Don't summarize what you
just did at length — they can see the diff. End-of-turn: 1–2 sentences on what
changed and what to do next.

Don't pile on features beyond what was asked. Don't refactor unrelated code.
Don't add backwards-compat shims. Match the scope of the request.

For any web-app change, the deploy step is:

```powershell
cd "c:\Users\jacob\Desktop\Blazepod hack\web"
vercel --yes --prod
```

Production alias is stable: `https://web-psi-silk-uz4uykpau7.vercel.app`.

## Project commands

```powershell
# Python tests (no hardware needed)
PYTHONPATH=src python -m pytest tests/ -q

# JS protocol tests (no hardware needed)
node web/js/protocol.test.mjs

# Python desktop GUI (needs hardware)
python -m blazepod.ui.qt

# Live BLE tests (needs pods nearby + awake)
python tests/live_ble_tests.py <test-name>
```
