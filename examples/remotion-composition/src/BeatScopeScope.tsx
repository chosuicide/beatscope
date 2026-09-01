import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { frameTime, sceneState } from "./state.js";

// Offline composition: structure drives layout. The scene's composition
// channels place three structural blocks; boundary transitions ease the
// layout, so the visual responds to song structure, not only amplitude.
const BLOCK_TONES: Record<string, [string, string, string]> = {
  A: ["#232833", "#5d7d8f", "#cfdde2"],
  B: ["#2e2018", "#a8613c", "#f0bd8c"],
  C: ["#241f2e", "#6f5f8f", "#d8cfdd"],
};

const BeatScopeScope: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const time = frameTime(frame, fps);
  const state = sceneState(time);

  const tones = BLOCK_TONES[state.scene.family] ?? BLOCK_TONES.A;
  const { spread, twist, orbit, void: voidChannel } = state.composition;
  const motion = state.transition.impulse;
  const columns = 2 + Math.round(state.composition.flow * 2);
  const blockCount = columns * 3;
  const blocks = [];
  for (let i = 0; i < blockCount; i += 1) {
    const row = Math.floor(i / columns);
    const column = i % columns;
    const tone = tones[(row + state.scene.variant) % tones.length];
    const lift = state.timing.low * 60 * (1 - row * 0.25);
    blocks.push(
      <div
        key={i}
        style={{
          position: "absolute",
          left: `${8 + column * (84 / columns) + spread * 6 + orbit * 4 * Math.sin(state.timing.barPhase * Math.PI * 2 + i)}%`,
          top: `${12 + row * 26 - lift * 0.2}%`,
          width: `${76 / columns}%`,
          height: `${18 + state.timing.mid * 8}%`,
          background: tone,
          opacity: 0.55 + state.timing.high * 0.45,
          transform: `rotate(${twist * 6 + motion * 2}deg) translateY(${-lift}px)`,
          borderRadius: 6,
        }}
      />,
    );
  }

  const voidOffset = voidChannel * 40;
  return (
    <AbsoluteFill style={{ background: "#14161c", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          transform: `translateY(${voidOffset}px)`,
        }}
      >
        {blocks}
      </div>
    </AbsoluteFill>
  );
};

export default BeatScopeScope;
