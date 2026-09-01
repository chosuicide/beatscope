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
  const [shadow, accent, highlight] = framePalette(frame);
  context.fillStyle = shadow;
  context.fillRect(0, 0, size.width, size.height);
  const points = particlePoints(field, frame, size, reducedMotion());
  for (const point of points) {
    context.globalAlpha = Math.max(0, Math.min(1, point.alpha));
    context.fillStyle = point.sparkle ? highlight : accent;
    context.beginPath();
    context.arc(point.x, point.y, Math.max(0.4, point.radius), 0, Math.PI * 2);
    context.fill();
  }
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
