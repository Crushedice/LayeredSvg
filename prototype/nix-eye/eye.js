// Nix eye — blink and saccade timers for the layered eye in eye.css.
// Usage: const eye = await mountEye(rootEl); eye.setAffect('sharp');

// Order matters: index = how far the lid has closed.
export const FRAMES = ['blink-02', 'blink-03', 'blink-04', 'blink-05', 'blink-06', 'blink-07', 'blink-08', 'blink-09'];

// Which frames a blink steps through, and per-step timings in ms.
export const BLINK_STYLES = {
  anime: { frames: ['blink-05', 'blink-09'], closing: 50, closed: 70, opening: 50 },
  full:  { frames: ['blink-03', 'blink-05', 'blink-07', 'blink-09'], closing: 28, closed: 60, opening: 40 },
};

// Timing per affect. Seconds unless noted. Gaze values are % of the iris box.
export const AFFECTS = {
  idle:     { blinkEvery: [2.5, 6], double: .15, speed: 1,   saccadeEvery: [1, 3],    range: [14, 5], bias: [0, 0],    rest: null },
  sharp:    { blinkEvery: [3, 7],   double: .05, speed: .85, saccadeEvery: [1.4, 3],  range: [7, 3],  bias: [0, -1],   rest: null },
  engaged:  { blinkEvery: [2.2, 5], double: .25, speed: 1,   saccadeEvery: [.45, 1.3], range: [18, 6], bias: [0, 0],    rest: null },
  reticent: { blinkEvery: [3, 7],   double: .1,  speed: 1.2, saccadeEvery: [2.5, 5],  range: [4, 2],  bias: [-20, 7],  rest: 'blink-05' },
  flat:     { blinkEvery: [5, 9],   double: 0,   speed: 1.7, saccadeEvery: [3, 6],    range: [6, 2],  bias: [0, 2],    rest: null },
};

const rand = (a, b) => a + Math.random() * (b - a);

export async function mountEye(root, { blinkStyle = 'anime', onState } = {}) {
  const lids = new Map([...root.querySelectorAll('[data-frame]')].map(el => [el.dataset.frame, el]));
  const iris = root.querySelector('.nix-iris');
  await Promise.all([...root.querySelectorAll('img')].map(img => img.decode().catch(() => {})));

  const state = { affect: root.dataset.affect || 'idle', blinkStyle, frame: null, gaze: [0, 0], nextBlinkAt: 0 };
  let epoch = 0;
  const timers = new Set();
  const emit = () => onState?.({ ...state, gaze: [...state.gaze] });
  const preset = () => AFFECTS[state.affect] ?? AFFECTS.idle;

  const wait = (ms, my) => new Promise((resolve, reject) => {
    const t = setTimeout(() => { timers.delete(t); my === epoch ? resolve() : reject(); }, ms);
    timers.add(t);
  });

  function show(name) {
    if (state.frame === name) return;
    if (state.frame) lids.get(state.frame).hidden = true;
    if (name) lids.get(name).hidden = false;
    state.frame = name;
    emit();
  }

  function look(x, y) {
    state.gaze = [x, y];
    iris.style.setProperty('--gx', x.toFixed(2));
    iris.style.setProperty('--gy', y.toFixed(2));
    emit();
  }

  function saccadeTarget() {
    const { bias, range } = preset();
    return [bias[0] + rand(-range[0], range[0]), bias[1] + rand(-range[1], range[1])];
  }

  async function blinkOnce(my) {
    const s = BLINK_STYLES[state.blinkStyle];
    const k = preset().speed;
    const rest = preset().rest;
    const from = rest ? FRAMES.indexOf(rest) : -1;
    const closing = s.frames.filter(f => FRAMES.indexOf(f) > from);
    const opening = closing.slice(0, -1).reverse();
    for (const f of closing.slice(0, -1)) { show(f); await wait(s.closing * k, my); }
    show(closing.at(-1));
    if (Math.random() < .5) look(...saccadeTarget()); // gaze often shifts behind a blink
    await wait(s.closed * k, my);
    for (const f of opening) { show(f); await wait(s.opening * k, my); }
    show(rest);
  }

  async function blink(double = false, my = epoch) {
    await blinkOnce(my);
    if (double) { await wait(90, my); await blinkOnce(my); }
  }

  async function blinkLoop(my) {
    for (;;) {
      const p = preset();
      const ms = rand(...p.blinkEvery) * 1000;
      state.nextBlinkAt = performance.now() + ms;
      emit();
      await wait(ms, my);
      await blink(Math.random() < p.double, my);
    }
  }

  async function saccadeLoop(my) {
    for (;;) {
      look(...saccadeTarget());
      const hold = rand(...preset().saccadeEvery) * 1000;
      // a microsaccade or two while holding keeps it from looking frozen
      let left = hold;
      while (left > 700 && Math.random() < .45) {
        const t = rand(350, Math.min(left - 300, 1200));
        await wait(t, my);
        left -= t;
        look(state.gaze[0] + rand(-1.5, 1.5), state.gaze[1] + rand(-.8, .8));
      }
      await wait(left, my);
    }
  }

  function restart() {
    epoch++;
    timers.forEach(clearTimeout);
    timers.clear();
    const my = epoch;
    show(preset().rest);
    look(...saccadeTarget());
    blinkLoop(my).catch(() => {});
    saccadeLoop(my).catch(() => {});
  }

  restart();

  return {
    get state() { return { ...state }; },
    setAffect(name) {
      if (!AFFECTS[name]) throw new Error(`unknown affect: ${name}`);
      state.affect = root.dataset.affect = name;
      restart();
    },
    setBlinkStyle(name) {
      if (!BLINK_STYLES[name]) throw new Error(`unknown blink style: ${name}`);
      state.blinkStyle = name;
      restart();
    },
    blink(double = false) {
      // run a blink now, then resume the normal loops
      epoch++;
      timers.forEach(clearTimeout);
      timers.clear();
      const my = epoch;
      blink(double, my).then(() => { if (my === epoch) restart(); }).catch(() => {});
    },
    destroy() {
      epoch++;
      timers.forEach(clearTimeout);
      timers.clear();
    },
  };
}
