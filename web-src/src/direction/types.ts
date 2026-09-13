/**
 * Types for the `beatscope-direction-1` document.
 * These shapes follow the canonical registry, anchor and response rules.
 *
 * Determinism rules: no wall-clock in musical evaluation; scene
 * anchors resolve to exact media times; envelopes evaluate around each
 * event's original measured timestamp.
 */

export type LayerSystemKind = 'editorial-typography' | 'graphic-field' | 'media-slice';

export type TransitionKind = 'cut' | 'dissolve' | 'directional-wipe' | 'split-reveal' | 'hold-through';

export type BlendMode = 'normal' | 'multiply' | 'screen' | 'difference' | 'overlay';

/** Normalized crop window (fractions of the source frame, R2C2). */
export interface LayerCrop {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface LayerTransform {
  /** normalized composition coords (0..1 of board box) */
  x: number;
  y: number;
  w: number;
  h: number;
  rotation: number;
  /** present when the layer frames a sub-window of its source */
  crop?: LayerCrop;
}

export interface DirectionLayer {
  id: string;
  kind: LayerSystemKind;
  label: string;
  visible: boolean;
  locked: boolean;
  opacity: number;
  blend: BlendMode;
  transform: LayerTransform;
  /** system-specific properties interpreted by the system renderer */
  props: Record<string, unknown>;
}

export type DriverSpec =
  | {
      kind: 'ranked_onsets';
      band: 'low' | 'mid' | 'high';
      tier: 'primary' | 'secondary';
      max_events_per_bar: number;
      refractory_beats: number;
    }
  | { kind: 'beat_phase'; subdivision: 1 | 2 | 4 }
  | { kind: 'downbeat_impulse' }
  | { kind: 'energy_envelope'; band: 'low' | 'mid' | 'high' }
  | { kind: 'structure_boundary' }
  | { kind: 'scene_phase' }
  | { kind: 'transition_phase' };

export type MotionSpec =
  | { kind: 'scale_pulse'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'radial_expand'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'translate_recoil'; axis: [number, number]; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'translate_drift'; axis: [number, number]; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'rotate_recoil'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'crop_reveal'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'strip_offset'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'opacity_lift'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'opacity_fade'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'blur_focus'; amount: number; attack_seconds: number; release_seconds: number }
  | { kind: 'invert_palette'; amount: number; attack_seconds: number; release_seconds: number };

export interface ResponseChain {
  id: string;
  target_layer_id: string;
  label: string;
  driver: DriverSpec;
  motion: MotionSpec;
  /** 'unavailable' chains render honestly without fabricating data (§2.3) */
  unavailable_reason?: string;
}

/**
 * Half-open scene anchor (§4.2): bar anchors are 1-based with an exclusive
 * end bar; time anchors carry exact media seconds (no-grid fallback).
 */
export type SceneAnchor =
  | { kind: 'bars'; start_bar: number; end_bar: number }
  | { kind: 'time'; start_seconds: number; end_seconds: number };

export interface DirectionScene {
  id: string;
  title: string;
  /** neutral structure-family badge shown on the board foot */
  family: string;
  anchor: SceneAnchor;
  /** resolved exact media times (half-open; final scene includes duration) */
  start_time: number;
  end_time: number;
  transition_out: TransitionKind;
  layers: DirectionLayer[];
  responses: ResponseChain[];
}

export interface CompositionSettings {
  primary_ratio: '16:9' | '9:16' | '1:1';
  width: number;
  height: number;
  background: string;
}

export interface DirectionDocument {
  schema: 'beatscope-direction-1';
  version: string;
  project_id: string;
  project_title: string;
  source_rhythm_sha256: string;
  composition: CompositionSettings;
  theme: Record<string, unknown>;
  assets: unknown[];
  scenes: DirectionScene[];
  transitions: unknown[];
  diagnostics: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Workspace state never enters the direction document (§3.3).         */

export interface BoardBox {
  /** world units */
  x: number;
  y: number;
  w: number;
  /** body (art) height; head 34 and foot 26 are added by the renderer */
  bodyH: number;
  rotation: number;
}

export interface WorkspaceLayout {
  boards: Record<string, BoardBox>;
}

export interface WorkspaceDocument {
  schema: 'beathi-workspace-1';
  version: '0.12.0';
  project_id: string;
  source_rhythm_sha256: string;
  layout: WorkspaceLayout;
  camera: CameraState;
  selection: { sceneId: string | null; layerId: string | null; responseId: string | null };
  panels: { dockOpen: boolean; inspectorOpen: boolean; packageOpen: boolean };
}

export interface CameraState {
  x: number;
  y: number;
  zoom: number;
}
