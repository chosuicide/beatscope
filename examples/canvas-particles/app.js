// Canvas reference consumer: one requestAnimationFrame loop reads
// audio.currentTime, calls getBeatScopeFrame, and paints the planar
// particle field. The audio element owns transport; the visual only
// samples the current media time, so pause, seek, and replay are all
// exact by construction.
import { getBeatScopeFrame } from "../shared/fixture.beatscope/visual-state.js";
import { createParticleField, particlePoints, framePalette } from "./visual-field.js";

const canvas = document.getElementById("stage");
const context = canvas.getContext("2d");
const audio = document.getElementById("audio");
const playButton = document.getElementById("play");
const fileInput = document.getElementById("audio-file");
const seekInput = document.getElementById("seek");
const elapsedLabel = document.getElementById("elapsed");
const totalLabel = document.getElementById("total");
const reducedCheckbox = document.getElementById("reduced-motion");
const statusLabel = document.getElementById("status");

const field = createParticleField();

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
reducedCheckbox.checked = prefersReducedMotion();
reducedCheckbox.addEventListener("change", () => {
  statusLabel.textContent = reducedCheckbox.checked
    ? "Reduced motion on: displacement lowered, timing unchanged."
    : "Reduced motion off.";
});

function reducedMotion() {
  return reducedCheckbox.checked === true;
}

function duration() {
  return Number.isFinite(audio.duration) ? audio.duration : 0;
}

function clampToMediaTime(time) {
  const parsed = Number(time);
  if (!Number.isFinite(parsed) || parsed <= 0) return 0;
  const total = duration();
  return total > 0 ? Math.min(parsed, total) : parsed;
}

// Canvas size affects rendering only; timing state never depends on it.
function resize() {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
}
window.addEventListener("resize", resize);

function formatTime(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

function draw(frame, size) {
  const [, accent] = framePalette(frame);
  const timing = frame.timing;
  const scene = frame.scene;
  const impulse = timing.onset?.value ?? 0;
  const accentHit = timing.accent?.value ?? 0;
  context.fillStyle = "#f0efe9";
  context.fillRect(0, 0, size.width, size.height);
  const points = particlePoints(field, frame, size, reducedMotion());

  context.strokeStyle = "#151515";
  context.lineCap = "round";
  for (let row = 0; row < 30; row += 1) {
    const offset = row * 56;
    context.beginPath();
    for (let column = 0; column < 56; column += 1) {
      const point = points[offset + column];
      if (column === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    }
    const depth = row / 29;
    context.globalAlpha = 0.09 + (1 - depth) * 0.24 + impulse * 0.16;
    context.lineWidth = 0.45 + timing.low * 1.8 + (row % 6 === 0 ? 0.8 : 0);
    context.stroke();
  }

  context.globalAlpha = 0.25 + timing.high * 0.7;
  context.fillStyle = accent;
  for (let i = 0; i < 18; i += 1) {
    const x = ((i + timing.beatPhase) / 18) * size.width;
    const height = 8 + timing.high * 70 * ((i % 5) / 4);
    context.fillRect(x, size.height - height - 18, 1.2, height);
  }
  if (accentHit > 0) {
    context.globalAlpha = Math.min(0.78, accentHit * 0.7);
    const width = size.width * (0.08 + accentHit * 0.2);
    context.fillRect(size.width * timing.barPhase - width / 2, 0, width, size.height);
  }

  context.globalAlpha = 0.82;
  context.fillStyle = "#151515";
  context.font = "600 12px ui-monospace, SFMono-Regular, Consolas, monospace";
  context.fillText(`BAR ${String(timing.bar).padStart(2, "0")}  BEAT ${timing.beat}`, 18, 28);
  context.textAlign = "right";
  context.fillText(scene ? `${scene.scene.family}${scene.scene.variant ? "'" : ""}` : "LEGACY", size.width - 18, 28);
  context.textAlign = "left";
  context.globalAlpha = 1;
}

function frameAt(time) {
  return getBeatScopeFrame(time, { reducedMotion: reducedMotion() });
}

let seekDragging = false;

// The browser debug hook (beatscope-consumer-1): a thin testing surface
// over the same calls the render loop makes, frozen per the contract.
window.__BEATSCOPE_CONSUMER__ = Object.freeze({
  frameAt,
  seek: (time) => {
    audio.currentTime = clampToMediaTime(time);
  },
  pause: () => audio.pause(),
  resume: () => audio.play(),
  diagnostics: () => ({
    clock: "audio.currentTime",
    audioTime: audio.currentTime,
    duration: Number.isFinite(audio.duration) ? audio.duration : null,
    paused: audio.paused,
    reducedMotion: reducedMotion(),
    particleCount: field.length,
    package: "../shared/fixture.beatscope",
  }),
});

playButton.addEventListener("click", () => {
  if (audio.paused) {
    audio.play();
  } else {
    audio.pause();
  }
});

audio.addEventListener("play", () => {
  playButton.textContent = "Pause";
  playButton.setAttribute("aria-pressed", "true");
});
audio.addEventListener("pause", () => {
  playButton.textContent = "Play";
  playButton.setAttribute("aria-pressed", "false");
});
audio.addEventListener("ended", () => {
  playButton.textContent = "Replay";
  playButton.setAttribute("aria-pressed", "false");
});

fileInput.addEventListener("change", () => {
  const [file] = fileInput.files;
  if (!file) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(file);
  totalLabel.textContent = formatTime(0);
  statusLabel.textContent = `Loaded "${file.name}". Playback stays paused until you press Play.`;
  playButton.textContent = "Play";
});

// Seek is a native range input, so keyboard operation comes for free.
seekInput.addEventListener("input", () => {
  const total = duration();
  if (total <= 0) return;
  audio.currentTime = (Number(seekInput.value) / 1000) * total;
});

audio.addEventListener("loadedmetadata", () => {
  totalLabel.textContent = formatTime(duration());
  seekInput.value = "0";
});

function paint() {
  const time = audio.currentTime;
  const frame = frameAt(time);
  const size = { width: canvas.clientWidth, height: canvas.clientHeight };
  draw(frame, size);
  elapsedLabel.textContent = formatTime(time);
  if (Number.isFinite(audio.duration)) {
    totalLabel.textContent = formatTime(duration());
    if (!seekDragging) {
      seekInput.value = String(Math.round((time / duration()) * 1000));
    }
  }
  requestAnimationFrame(paint);
}

seekInput.addEventListener("pointerdown", () => {
  seekDragging = true;
});
window.addEventListener("pointerup", () => {
  seekDragging = false;
});

resize();
requestAnimationFrame(paint);
