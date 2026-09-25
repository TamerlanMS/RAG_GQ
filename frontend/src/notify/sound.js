// Звук нового сообщения — синтезируется Web Audio, без аудиофайла.
//
// Браузеры запрещают звук до первого действия пользователя на странице
// (autoplay policy), поэтому AudioContext создаётся/«размораживается» по
// первому клику или нажатию клавиши — см. unlockAudio().

let ctx = null;
let lastPlayed = 0;

function getContext() {
  if (ctx) return ctx;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  ctx = new Ctx();
  return ctx;
}

export function unlockAudio() {
  const c = getContext();
  if (c && c.state === "suspended") c.resume().catch(() => {});
}

// Два коротких тона вверх — узнаваемо и негромко.
export function playMessageSound() {
  const now = Date.now();
  if (now - lastPlayed < 1200) return; // пачка сообщений — один сигнал
  lastPlayed = now;

  const c = getContext();
  if (!c) return;
  if (c.state === "suspended") c.resume().catch(() => {});

  const t0 = c.currentTime + 0.01;
  [
    [880, 0],
    [1320, 0.13],
  ].forEach(([freq, offset]) => {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t0 + offset);
    gain.gain.exponentialRampToValueAtTime(0.18, t0 + offset + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + offset + 0.18);
    osc.connect(gain).connect(c.destination);
    osc.start(t0 + offset);
    osc.stop(t0 + offset + 0.2);
  });
}
