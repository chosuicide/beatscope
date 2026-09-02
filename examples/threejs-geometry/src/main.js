// Three.js reference consumer. One render loop reads audio.currentTime,
// asks the handoff package for the frame at that media time, and maps it
// through beatscope-mapping.js. Every object transform is a function of
// the current time and frame — never an accumulated delta — so seek and
// replay land on identical geometry.
import * as THREE from "three";
import { getBeatScopeFrame } from "../../shared/fixture.beatscope/visual-state.js";
import { mapFrame, familyColor, pointOpacity } from "./beatscope-mapping.js";
import { seededShell } from "./seeded-geometry.js";

const canvas = document.getElementById("stage");
const audio = document.getElementById("audio");
const playButton = document.getElementById("play");
const fileInput = document.getElementById("audio-file");
const seekInput = document.getElementById("seek");
const elapsedLabel = document.getElementById("elapsed");
const totalLabel = document.getElementById("total");
const reducedCheckbox = document.getElementById("reduced-motion");
const statusLabel = document.getElementById("status");
const fallback = document.getElementById("webgl-fallback");

let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
} catch (error) {
  fallback.hidden = false;
  statusLabel.textContent = `WebGL unavailable: ${error?.message || "renderer initialization failed"}`;
}

// Honest fallback when WebGL is unavailable or the context is lost.
canvas.addEventListener("webglcontextlost", (event) => {
  event.preventDefault();
  renderer = null;
  fallback.hidden = false;
  statusLabel.textContent = "WebGL context lost: rendering stopped, audio keeps playing.";
});

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(55, canvas.clientWidth / canvas.clientHeight, 0.1, 50);
camera.position.set(0, 0.4, 2.9);

const COUNT = 1400;
const SEED = 42;
const geometry = new THREE.BufferGeometry();
geometry.setAttribute("position", new THREE.BufferAttribute(seededShell(COUNT, SEED), 3));
const material = new THREE.PointsMaterial({ size: 0.035, transparent: true, opacity: 0.85 });
const cloud = new THREE.Points(geometry, material);
scene.add(cloud);

function reducedMotion() {
  return reducedCheckbox.checked === true;
}
reducedCheckbox.checked = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function duration() {
  return Number.isFinite(audio.duration) ? audio.duration : 0;
}

function frameAt(time) {
  return getBeatScopeFrame(time, { reducedMotion: reducedMotion() });
}

window.__BEATSCOPE_CONSUMER__ = Object.freeze({
  frameAt,
  seek: (time) => {
    const parsed = Number(time);
    const total = duration();
    audio.currentTime = Number.isFinite(parsed) && parsed > 0 && total > 0 ? Math.min(parsed, total) : 0;
  },
  pause: () => audio.pause(),
  resume: () => audio.play(),
  diagnostics: () => ({
    clock: "audio.currentTime",
    audioTime: audio.currentTime,
    duration: Number.isFinite(audio.duration) ? audio.duration : null,
    paused: audio.paused,
    reducedMotion: reducedMotion(),
    seed: SEED,
    particleCount: COUNT,
    drawCalls: renderer?.info.render.calls ?? 0,
  }),
});

playButton.addEventListener("click", () => {
  if (audio.paused) audio.play();
  else audio.pause();
});
audio.addEventListener("play", () => {
  playButton.textContent = "Pause";
  playButton.setAttribute("aria-pressed", "true");
});
audio.addEventListener("pause", () => {
  playButton.textContent = "Play";
  playButton.setAttribute("aria-pressed", "false");
});
fileInput.addEventListener("change", () => {
  const [file] = fileInput.files;
  if (!file) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(file);
  statusLabel.textContent = `Loaded "${file.name}". Playback stays paused until you press Play.`;
});
seekInput.addEventListener("input", () => {
  const total = duration();
  if (total > 0) audio.currentTime = (Number(seekInput.value) / 1000) * total;
});
audio.addEventListener("loadedmetadata", () => {
  seekInput.value = "0";
});

function formatTime(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${(safe - minutes * 60).toFixed(1).padStart(4, "0")}`;
}

function resize() {
  if (!renderer) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  renderer.setSize(width * ratio, height * ratio, false);
  camera.aspect = width / Math.max(1, height);
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

function paint() {
  const time = audio.currentTime;
  const frame = frameAt(time);
  const mapped = mapFrame(frame, time);
  const motion = reducedMotion() ? 0.25 : 1;

  // Rotation and scale derive from t and the frame — never from deltas.
  cloud.rotation.y = mapped.cameraPhase + mapped.twist * Math.PI * motion;
  cloud.rotation.x = frame.timing.beatPhase * Math.PI * 0.15 * motion;
  const accent = frame.timing.accent?.value ?? 0;
  const scale = mapped.scale * (1 + accent * 0.12 * motion);
  cloud.scale.setScalar(scale);
  camera.position.z = 2.9 + Math.sin(mapped.cameraPhase * 0.7) * 0.3 * motion;
  camera.lookAt(0, 0, 0);

  material.color.setHex(familyColor(frame));
  material.opacity = Math.max(0, Math.min(1, pointOpacity(frame, reducedMotion())));

  if (renderer) renderer.render(scene, camera);
  elapsedLabel.textContent = formatTime(time);
  if (Number.isFinite(audio.duration)) {
    totalLabel.textContent = formatTime(duration());
    seekInput.value = String(Math.round((time / duration()) * 1000));
  }
  requestAnimationFrame(paint);
}

resize();
requestAnimationFrame(paint);
