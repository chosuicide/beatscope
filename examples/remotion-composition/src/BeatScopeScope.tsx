import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { frameTime, sceneState } from "./state.js";

const INK = "#10100f";
const PAPER = "#f1f0e9";
const SIGNAL = "#e23d24";

function pad(value: number, width = 2) {
  return String(Math.max(0, Math.floor(value))).padStart(width, "0");
}

const BeatScopeScope: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const time = frameTime(frame, fps);
  const state = sceneState(time);

  const family = state.scene.family || "A";
  const variant = state.scene.variant > 0 ? "′" : "";
  const label = `${family}${variant}`;
  const boundary = state.transition.cross;
  const beat = state.timing.accent;
  const pulse = Math.max(boundary, beat * 0.72);
  const split = 42 + state.composition.spread * 8;
  const seconds = Math.floor(time);
  const timecode = `${pad(seconds / 60)}:${pad(seconds % 60)}:${pad((time % 1) * fps)}`;
  const redWidth = 7 + state.timing.high * 31;
  const wordOffset = (state.timing.barPhase - 0.5) * 54;

  return (
    <AbsoluteFill
      style={{
        background: PAPER,
        color: INK,
        overflow: "hidden",
        fontFamily: "Arial Narrow, Arial, sans-serif",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: INK,
          clipPath: `polygon(${split}% 0, 100% 0, 100% 100%, ${split - boundary * 11}% 100%)`,
        }}
      />

      <div
        style={{
          position: "absolute",
          left: 0,
          top: `${18 + state.timing.mid * 22}%`,
          width: `${redWidth}%`,
          height: 12 + pulse * 34,
          background: SIGNAL,
          transform: `translateX(${-12 + pulse * 22}%)`,
        }}
      />

      <div
        style={{
          position: "absolute",
          left: "5%",
          top: "5%",
          fontFamily: "Courier New, monospace",
          fontSize: 22,
          letterSpacing: 3,
        }}
      >
        BEATSCOPE / OFFLINE FRAME
      </div>

      <div
        style={{
          position: "absolute",
          left: "5%",
          top: "17%",
          width: "36%",
          fontSize: 270,
          fontWeight: 900,
          lineHeight: 0.78,
          letterSpacing: -24,
          transform: `translateX(${wordOffset}px) scaleX(${0.86 + state.timing.low * 0.22})`,
          transformOrigin: "left center",
        }}
      >
        {label}
      </div>

      <div
        style={{
          position: "absolute",
          left: "5%",
          bottom: "8%",
          display: "flex",
          gap: 32,
          alignItems: "baseline",
          fontFamily: "Courier New, monospace",
        }}
      >
        <span style={{ color: SIGNAL, fontSize: 46, fontWeight: 700 }}>{timecode}</span>
        <span style={{ fontSize: 18, letterSpacing: 2 }}>
          PHASE {Math.round(state.scene.phase * 100)}%
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          right: "4%",
          top: "9%",
          width: "50%",
          color: PAPER,
          textAlign: "right",
          fontSize: 34,
          letterSpacing: 8,
          fontWeight: 700,
          transform: `translateY(${boundary * 28}px)`,
        }}
      >
        STRUCTURE {label}
      </div>

      <div
        style={{
          position: "absolute",
          right: "4%",
          bottom: "8%",
          width: "48%",
          height: 144,
          display: "grid",
          gridTemplateColumns: "repeat(16, 1fr)",
          gap: 8,
          alignItems: "end",
        }}
      >
        {Array.from({ length: 16 }, (_, index) => {
          const alternating = index % 3 === 0 ? state.timing.high : state.timing.mid;
          const phase = (state.timing.beatPhase + index / 16) % 1;
          const height = 14 + alternating * 70 + (1 - phase) * beat * 45;
          return (
            <div
              key={index}
              style={{
                height,
                background: index % 5 === 0 ? SIGNAL : PAPER,
                opacity: 0.38 + alternating * 0.62,
              }}
            />
          );
        })}
      </div>

      <div
        style={{
          position: "absolute",
          inset: 0,
          border: `${2 + boundary * 13}px solid ${boundary > 0.45 ? SIGNAL : "transparent"}`,
          pointerEvents: "none",
        }}
      />
    </AbsoluteFill>
  );
};

export default BeatScopeScope;
