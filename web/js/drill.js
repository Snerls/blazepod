// Drill engine — port of src/blazepod/drills/custom.py.
// Async/await throughout; stations run in parallel via Promise.all.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const choice = (arr) => arr[Math.floor(Math.random() * arr.length)];
const uniform = (lo, hi) => lo + Math.random() * (hi - lo);

export const LightsOut    = Object.freeze({ HIT: 'hit', TIMEOUT: 'timeout', HIT_AND_TIMEOUT: 'hit_and_timeout' });
export const LightDelay   = Object.freeze({ NONE: 'none', FIXED: 'fixed', RANDOM: 'random' });
export const DurationMode = Object.freeze({ TIME: 'time', HIT_COUNT: 'hit_count', TIME_AND_HIT_COUNT: 'time_and_hit_count' });

export function makeStats(drillName) {
  return {
    drillName,
    reactionTimesMs: [],
    hits: 0,
    misses: 0,
    totalTimeMs: 0,
    notes: [],
    subscores: {},
  };
}

export function statsSummary(s) {
  const attempts = s.hits + s.misses;
  const accuracy = attempts ? s.hits / attempts : 0;
  const rt = s.reactionTimesMs;
  const mean   = rt.length ? rt.reduce((a, b) => a + b, 0) / rt.length : 0;
  const sorted = [...rt].sort((a, b) => a - b);
  const median = sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
  return {
    attempts, accuracy,
    meanMs: mean, medianMs: median,
    bestMs: sorted[0] || 0, worstMs: sorted[sorted.length - 1] || 0,
  };
}

// AbortSignal-aware queue: each station owns one of these.
class TapBox {
  constructor() { this.q = []; this.waiters = []; }
  put(value) {
    if (this.waiters.length) {
      const { resolve } = this.waiters.shift();
      resolve(value);
    } else {
      this.q.push(value);
    }
  }
  // Resolves with `value` or `null` on timeout/abort.
  async take(timeoutMs, signal) {
    if (this.q.length) return this.q.shift();
    return new Promise((resolve) => {
      const w = { resolve };
      this.waiters.push(w);
      const cleanup = () => {
        const i = this.waiters.indexOf(w);
        if (i !== -1) this.waiters.splice(i, 1);
      };
      let to;
      if (timeoutMs != null && timeoutMs >= 0) {
        to = setTimeout(() => { cleanup(); resolve(null); }, timeoutMs);
      }
      if (signal) {
        signal.addEventListener('abort', () => { clearTimeout(to); cleanup(); resolve(null); }, { once: true });
      }
    });
  }
}

class Station {
  constructor(idx, pods, player) {
    this.idx = idx;
    this.pods = pods;
    this.player = player;
    this.target = null;
    this.box = new TapBox();
    this.stats = makeStats(player.name);
    this._cursor = 0;
  }
  nextColor() {
    const c = this.player.colors[this._cursor % this.player.colors.length];
    this._cursor++;
    return c;
  }
  pickTarget() {
    if (this.target && this.pods.length > 1) {
      const others = this.pods.filter((p) => p.address !== this.target.address);
      return choice(others);
    }
    return choice(this.pods);
  }
}

export class CustomDrill {
  constructor(manager, config, { onUpdate } = {}) {
    this.manager = manager;
    this.config = config;
    this.onUpdate = onUpdate || (() => {});
    this.stats = makeStats('Custom');
    this._abort = new AbortController();

    const pods = manager.values();
    const need = config.stations * config.podsPerStation;
    if (need > pods.length) {
      throw new Error(`need ${need} pods (${config.stations} × ${config.podsPerStation}), only ${pods.length} connected`);
    }
    if (!config.players || config.players.length === 0) {
      throw new Error('at least one player required');
    }

    this.stations = [];
    for (let s = 0; s < config.stations; s++) {
      const slice = pods.slice(s * config.podsPerStation, (s + 1) * config.podsPerStation);
      const player = config.players[s % config.players.length];
      this.stations.push(new Station(s, slice, player));
    }
    this._addrToStation = new Map();
    for (const st of this.stations) for (const p of st.pods) this._addrToStation.set(p.address, st);
  }

  abort() { this._abort.abort(); }

  async run() {
    const start = performance.now();
    const unsub = this.manager.onTap((pod, ev) => this._onTap(pod, ev));
    try {
      for (let cycle = 0; cycle < this.config.cycles; cycle++) {
        if (this._abort.signal.aborted) break;
        if (cycle > 0) this.stats.notes.push(`--- cycle ${cycle + 1} ---`);
        await this._runCycle();
      }
    } finally {
      unsub();
      await this.manager.allOff();
      // Aggregate
      for (const st of this.stations) {
        this.stats.subscores[`${st.player.name} (station ${st.idx + 1})`] = st.stats;
        this.stats.hits  += st.stats.hits;
        this.stats.misses += st.stats.misses;
        this.stats.reactionTimesMs.push(...st.stats.reactionTimesMs);
      }
      this.stats.totalTimeMs = Math.round(performance.now() - start);
    }
    return this.stats;
  }

  async _runCycle() {
    const cfg = this.config;
    const cycleAbort = new AbortController();
    const onParentAbort = () => cycleAbort.abort();
    this._abort.signal.addEventListener('abort', onParentAbort, { once: true });

    let totalHits = 0;
    const hitCap = (cfg.durationMode === DurationMode.HIT_COUNT || cfg.durationMode === DurationMode.TIME_AND_HIT_COUNT)
      ? cfg.durationHitCount : null;

    let timeTimer = null;
    if (cfg.durationMode === DurationMode.TIME || cfg.durationMode === DurationMode.TIME_AND_HIT_COUNT) {
      timeTimer = setTimeout(() => cycleAbort.abort(), cfg.durationTimeS * 1000);
    }

    const runStation = async (st) => {
      while (!cycleAbort.signal.aborted) {
        const target = st.pickTarget();
        st.target = target;
        const [r, g, b] = st.nextColor();
        const offOnTap = (cfg.lightsOut === LightsOut.HIT || cfg.lightsOut === LightsOut.HIT_AND_TIMEOUT);
        try { await target.setColor(r, g, b, { offOnTap }); }
        catch (e) { console.warn('setColor failed', e); st.target = null; await sleep(200); continue; }

        const timeoutMs = (cfg.lightsOut === LightsOut.TIMEOUT || cfg.lightsOut === LightsOut.HIT_AND_TIMEOUT)
          ? cfg.timeoutS * 1000 : null;
        const ev = await st.box.take(timeoutMs, cycleAbort.signal);
        st.target = null;

        if (cycleAbort.signal.aborted) break;

        if (ev) {
          st.stats.hits++;
          st.stats.reactionTimesMs.push(ev.elapsedMs);
          totalHits++;
          if (hitCap != null && totalHits >= hitCap) cycleAbort.abort();
        } else {
          st.stats.misses++;
          try { await target.turnOff(); } catch {}
        }
        this.onUpdate();

        const delayMs = this._delayMs();
        if (delayMs > 0) await new Promise((res) => {
          const t = setTimeout(res, delayMs);
          cycleAbort.signal.addEventListener('abort', () => { clearTimeout(t); res(); }, { once: true });
        });
      }
    };

    try {
      await Promise.all(this.stations.map(runStation));
    } finally {
      if (timeTimer) clearTimeout(timeTimer);
      this._abort.signal.removeEventListener('abort', onParentAbort);
    }
  }

  _onTap(pod, ev) {
    if (!ev.hitLitPod) return;
    const st = this._addrToStation.get(pod.address);
    if (!st) return;
    if (st.target && st.target.address === pod.address) {
      st.box.put(ev);
    } else {
      st.stats.misses++;
      this.onUpdate();
    }
  }

  _delayMs() {
    switch (this.config.lightDelay) {
      case LightDelay.NONE:   return 0;
      case LightDelay.FIXED:  return Math.max(0, this.config.lightDelayFixedS) * 1000;
      case LightDelay.RANDOM: {
        const lo = Math.max(0, this.config.lightDelayMinS);
        const hi = Math.max(lo, this.config.lightDelayMaxS);
        return uniform(lo, hi) * 1000;
      }
    }
    return 0;
  }
}

export function defaultConfig() {
  return {
    stations: 1,
    podsPerStation: 6,
    players: [{ name: 'Player 1', colors: [[255, 255, 255]] }],
    lightsOut: LightsOut.HIT,
    timeoutS: 3.0,
    lightDelay: LightDelay.NONE,
    lightDelayFixedS: 1.0,
    lightDelayMinS: 0.5,
    lightDelayMaxS: 2.0,
    durationMode: DurationMode.TIME,
    durationTimeS: 60,
    durationHitCount: 50,
    cycles: 1,
  };
}
