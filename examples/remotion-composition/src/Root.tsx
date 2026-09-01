import { Composition } from "remotion";
import BeatScopeScope from "./BeatScopeScope";
import { compositionDuration } from "./state.js";

// Duration derives from the package duration and the target fps; the
// same second maps to the same BeatScope state at 24, 30, or 60 fps.
export const RemotionRoot = () => (
  <Composition
    id="BeatScopeScope"
    component={BeatScopeScope}
    durationInFrames={compositionDuration(30)}
    fps={30}
    width={1280}
    height={720}
  />
);
