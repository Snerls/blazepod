# BlazePod controller (no subscription)

A Python desktop app that drives BlazePod reaction pods over BLE without the official app or subscription. Reaction-time data stays local — no cloud, no account.

The BLE protocol was reverse-engineered by [sasodoma/blazepod-hacking](https://github.com/sasodoma/blazepod-hacking); this project ports their C reference to Python and builds a usable controller on top.

> **Disclaimer:** Not affiliated with PLAY COYOTTA LTD or BlazePod. BlazePod® is a registered trademark of PLAY COYOTTA LTD. Use of your own hardware over BLE is at your own risk.

## Requirements

- Python 3.11+
- A Bluetooth Low Energy adapter (built-in on most laptops; cheap USB dongles work)
- One or more BlazePod pods, charged and powered on
- Windows / macOS / Linux (Bleak handles all three)

## Install

```powershell
python -m pip install -e ".[dev]"
```

If you only want the CLI examples and not the TUI, `pip install bleak` is enough.

## Quickstart

```powershell
# 1) Verify the BLE stack sees your pods
python examples/scan.py

# 2) Run the protocol smoke test against one pod
python examples/blink.py

# 3) Launch the desktop GUI
python -m blazepod.ui.qt
# (or `blazepod` if you `pip install -e .`'d)
# Terminal version still available: python -m blazepod.ui.tui
```

## What's in the box

```
src/blazepod/
  protocol.py     # UUIDs, auth CRC, color encoder, tap decoder
  pod.py          # one BLE connection, handshake, notifications
  manager.py      # discovery + parallel multi-pod connections + tap queue
  drills/         # Random Light, Sequence, Color Match
  ui/qt.py        # PyQt6 desktop GUI (default)
  ui/tui.py       # Textual terminal interface
examples/
  scan.py         # list nearby pods (use `--all` to see every BLE device)
  blink.py        # connect to one pod, cycle colors, print taps
tests/
  test_protocol.py  # 23 tests; cross-checks CRC against an independent C port
```

## Drills

- **Random Light** — light a random pod white, time the tap, repeat. Reports mean/median/best/worst reaction time.
- **Sequence** — light pods one at a time in a random order; tap each as it lights up. Wrong-pod taps count as misses.
- **Color Match** — light all pods at once, target in green, distractors in red. Tap only the green one.

Each drill returns a `Stats` object with hits, misses, accuracy, and per-trial reaction times in milliseconds (measured by the pod itself, so no BLE-latency error).

## Protocol cheatsheet

| Purpose | Service | Characteristic |
|---|---|---|
| Auth (UART RX) | `6e400001-…` | `6e400002-…` — write 7 bytes after connect |
| Set color | `50c97bfa-…` | `50c912a2-…` — `[G, B, R]` (+ optional `0x01` to auto-off on tap) |
| Tap notify | `50c928bd-…` | `50c9727e-…` — 8-byte: `[state, ms LE×4, ?×3]` |

Auth payload: `b"sea" + crc32_variant(last 5 bytes of mfr-data)`. Full algorithm in [protocol.py](src/blazepod/protocol.py).

## Troubleshooting

- **No pods discovered.** Run `python examples/scan.py --all -v` to see every BLE device. If your pods don't advertise the documented service UUIDs, file an issue with the manufacturer-data hex so the heuristic can be widened.
- **Connect succeeds but pod doesn't light.** Auth probably failed silently. Confirm the manufacturer-specific data has at least 5 bytes; check `blazepod.log` for the auth payload that was sent.
- **Some pods fail to connect when running the drill.** Cheap BLE adapters cap at 3–4 simultaneous connections. Try fewer pods, or a better adapter.

## Development

```powershell
PYTHONPATH=src python -m pytest tests/ -v
```
