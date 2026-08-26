/**
 * Audio playback, transient preview, and loop management.
 */

import { state, setPlayback } from './state.js';
import { timeAtBar, metrics } from './grid.js';

let audioElement = null;
let previewTimer = null;
let wasPlayingBeforePreview = false;

export function initAudio(element) {
  audioElement = element;

  audioElement.ontimeupdate = () => {
    const time = audioElement.currentTime;
    setPlayback(time, !audioElement.paused);

    // Loop check
    if (state.loop && state.project) {
      let loopStart;
      let loopEnd;
      if (state.loopSelection) {
        const timing = metrics(state.project, state.subdivision, state.adjustments);
        loopStart = timing.origin + state.loopSelection.start * timing.step;
        loopEnd = timing.origin + (state.loopSelection.end + 1) * timing.step;
      } else {
        loopStart = timeAtBar(state.startBar + 1, state.project, state.adjustments);
        loopEnd = timeAtBar(state.startBar + state.viewBars + 1, state.project, state.adjustments);
      }
      if (time >= loopEnd - 0.015) {
        audioElement.currentTime = loopStart;
      }
    }
  };

  audioElement.onplay = () => {
    setPlayback(audioElement.currentTime, true);
  };

  audioElement.onpause = () => {
    setPlayback(audioElement.currentTime, false);
  };

  audioElement.onended = () => {
    setPlayback(audioElement.currentTime, false);
  };

  return audioElement;
}

export function setAudioSource(src) {
  if (!audioElement) return;
  audioElement.src = src;
  audioElement.load();
}

export function play() {
  if (!audioElement || !audioElement.src) return;
  audioElement.play().catch(() => {});
}

export function pause() {
  if (!audioElement) return;
  audioElement.pause();
}

export function togglePlay() {
  if (!audioElement || !audioElement.src) return;
  if (audioElement.paused) {
    play();
  } else {
    pause();
  }
}

export function seek(time) {
  if (!audioElement) return;
  audioElement.currentTime = Math.max(0, Number(time) || 0);
  setPlayback(audioElement.currentTime, !audioElement.paused);
}

export function previewTransient(rawTime) {
  if (!audioElement || !audioElement.src) return;
  clearTimeout(previewTimer);

  if (!previewTimer) {
    wasPlayingBeforePreview = !audioElement.paused;
  }

  audioElement.currentTime = Math.max(0, Number(rawTime) - 0.05);
  audioElement.play().catch(() => {});

  previewTimer = setTimeout(() => {
    previewTimer = null;
    if (!wasPlayingBeforePreview) {
      audioElement.pause();
    }
  }, 140);
}
