// Multi-pod orchestration + tap dispatch — port of src/blazepod/manager.py.
// Tap dispatch uses an EventTarget-based queue ("listeners + per-station boxes").

import { Pod } from './pod.js';

export class PodManager {
  constructor() {
    this.pods = new Map();         // address -> Pod
    this._listeners = new Set();   // (pod, ev) -> void
  }

  get size() { return this.pods.size; }
  values() { return Array.from(this.pods.values()); }

  add(pod) {
    pod.onTap((p, ev) => this._dispatch(p, ev));
    this.pods.set(pod.address, pod);
  }

  remove(address) {
    const pod = this.pods.get(address);
    if (pod) pod.disconnect();
    this.pods.delete(address);
  }

  onTap(cb) {
    this._listeners.add(cb);
    return () => this._listeners.delete(cb);
  }

  clearTapListeners() { this._listeners.clear(); }

  _dispatch(pod, ev) {
    for (const cb of this._listeners) {
      try { cb(pod, ev); } catch (e) { console.warn('manager listener threw', e); }
    }
  }

  async allColor(r, g, b, opts) {
    await Promise.all(this.values().map((p) => p.setColor(r, g, b, opts)));
  }

  async allOff() {
    await Promise.allSettled(this.values().map((p) => p.turnOff()));
  }

  async disconnectAll() {
    await Promise.allSettled(this.values().map((p) => p.disconnect()));
    this.pods.clear();
  }

  async identifyEach({ r = 255, g = 0, b = 0, flashes = 3, gapMs = 600, onPod } = {}) {
    for (const pod of this.values()) {
      if (onPod) try { onPod(pod); } catch {}
      await pod.flash(r, g, b, { count: flashes });
      await new Promise((r2) => setTimeout(r2, gapMs));
    }
  }
}
