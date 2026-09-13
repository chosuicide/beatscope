/**
 * Editor state: one reducer, typed commands with apply/invert (plan §3.6).
 * Loading, playback ticks, hover and camera moves never enter history.
 * Authored document/workspace changes go through DirectionCommand so every
 * edit is one undo transaction.
 */
import { createContext, useContext, useMemo, useReducer, useRef, type Dispatch, type ReactNode } from 'react';
import type { DirectionDocument, DirectionLayer, ResponseChain, WorkspaceDocument, WorkspaceLayout } from '../direction/types';
import type { DirectionCommand } from '../direction/commands';
import { demoDocument, demoLayout } from '../demo/document';
import { demoRhythm, type DemoRhythm } from '../demo/rhythm';

/* All command factories live in ../direction/commands (pure, node-testable);
 * the store owns the history that commits them. Re-exported here so editor
 * components keep a single import site. */
export {
  moveBoardCommand,
  rotateBoardCommand,
  scaleBoardCommand,
  setLayerCropCommand,
  setLayerSourceCommand,
  markAssetMissingCommand,
  setResponseAmountCommand,
  addResponseCommand,
  removeResponseCommand,
  insertResponseCommand,
  setResponseDriverCommand,
  setResponseMotionCommand,
  assignResponseLayerCommand,
  toggleLayerVisibleCommand,
  toggleLayerLockedCommand,
  renameSceneCommand,
  splitSceneCommand,
  mergeSceneCommand,
  setPrimaryRatioCommand,
  compositeCommand,
  restoreDocumentCommand,
} from '../direction/commands';
export type { DirectionCommand } from '../direction/commands';

export type BootStatus = 'booting' | 'loading-project' | 'recovering-draft' | 'ready' | 'read-only-demo' | 'conflict' | 'fatal';

export interface Toast {
  id: string;
  text: string;
}

export interface ProposalChange {
  sign: '+' | '±' | '−';
  scene: string;
  system: string;
  detail?: string;
  before?: string;
  after?: string;
}

export interface ProposalPreview {
  scene: string;
  rect: { x: number; y: number; w: number; h: number }; // fractions of the board body
  label: string;
}

export interface Proposal {
  index: number;
  intent: string;
  scope: string;
  basis: string;
  changes: ProposalChange[];
  rawLines: string[];
  preview?: ProposalPreview[];
}

export type ProposalState = 'pending' | 'applied' | 'rejected' | 'hidden';

export interface AppState {
  boot: BootStatus;
  doc: DirectionDocument;
  rhythm: DemoRhythm;
  /** v0.11 response relevance keyed by onset id (null when unavailable) */
  relevance: Map<string, number> | null;
  layout: WorkspaceLayout;
  selection: { sceneId: string | null; layerId: string | null; responseId: string | null };
  camera: { x: number; y: number; zoom: number };
  transport: {
    time: number;
    playing: boolean;
    loopStart: number | null;
    loopEnd: number | null;
    /** Explicitly keep one edit board live while playback moves elsewhere. */
    pinnedSceneId: string | null;
  };
  coach: { visible: boolean; step: 1 | 2 | 3 };
  panels: { dockOpen: boolean; inspectorOpen: boolean; packageOpen: boolean };
  saveState: 'saved' | 'saving' | 'offline' | 'conflict';
  language: 'en' | 'zh-CN';
  webglAvailable: boolean;
  toasts: Toast[];
  proposal: Proposal | null;
  proposalState: ProposalState;
  /** legacy-shape project facts for the frozen WebMCP tools */
  legacyProject: unknown;
}

export type Action =
  | { type: 'boot'; status: BootStatus }
  | {
      type: 'doc-loaded';
      doc: DirectionDocument;
      rhythm?: DemoRhythm | null;
      workspace?: WorkspaceDocument | null;
      relevance?: Map<string, number> | null;
    }
  | { type: 'command'; command: DirectionCommand }
  | { type: 'undo' }
  | { type: 'redo' }
  | { type: 'select'; sceneId: string | null; layerId?: string | null; responseId?: string | null }
  | { type: 'camera'; x: number; y: number; zoom: number }
  | { type: 'transport-time'; time: number }
  | { type: 'transport-play'; playing: boolean }
  | { type: 'transport-loop'; start: number | null; end: number | null }
  | { type: 'live-pin'; sceneId: string | null }
  | { type: 'coach'; visible?: boolean; step?: 1 | 2 | 3 }
  | { type: 'panels'; dockOpen?: boolean; inspectorOpen?: boolean; packageOpen?: boolean }
  | { type: 'language'; language: 'en' | 'zh-CN' }
  | { type: 'webgl'; available: boolean }
  | { type: 'save-state'; state: AppState['saveState'] }
  | { type: 'toast'; text: string }
  | { type: 'toast-expire'; id: string }
  | { type: 'proposal'; proposal: Proposal | null; state: ProposalState };

interface History {
  past: DirectionCommand[];
  future: DirectionCommand[];
}

export interface Store {
  state: AppState;
  history: History;
  dispatch: Dispatch<Action>;
  getState: () => AppState;
}

const HISTORY_CAP = 100;

export const initialAppState: AppState = {
  boot: 'booting',
  doc: demoDocument,
  rhythm: demoRhythm(),
  relevance: null,
  layout: demoLayout,
  selection: { sceneId: null, layerId: null, responseId: null },
  camera: { x: 0, y: 0, zoom: 0.62 },
  transport: { time: 12.4, playing: false, loopStart: null, loopEnd: null, pinnedSceneId: null },
  coach: { visible: true, step: 1 },
  panels: { dockOpen: true, inspectorOpen: false, packageOpen: false },
  saveState: 'saved',
  language: 'en',
  webglAvailable: true,
  toasts: [],
  proposal: null,
  proposalState: 'hidden',
  legacyProject: null,
};

export function reducer(state: AppState, action: Action, history: History): { state: AppState; history: History } {
  switch (action.type) {
    case 'boot':
      return { state: { ...state, boot: action.status }, history };
    case 'doc-loaded':
      // loading replaces the document and clears history: undo never steps
      // across a project load (§3.6)
      return {
        state: action.workspace
          ? { ...state, doc: action.doc, rhythm: action.rhythm ?? state.rhythm, relevance: action.rhythm === null ? null : (action.relevance ?? null), layout: action.workspace.layout, camera: action.workspace.camera, transport: { ...state.transport, pinnedSceneId: null },
              selection: action.workspace.selection, panels: action.workspace.panels }
          : { ...state, doc: action.doc, rhythm: action.rhythm ?? state.rhythm, relevance: action.rhythm === null ? null : (action.relevance ?? null), transport: { ...state.transport, pinnedSceneId: null } },
        history: { past: [], future: [] },
      };
    case 'command': {
      const before = state;
      const next = action.command.apply(state);
      return {
        state: next,
        history: { past: [...history.past, { ...action.command, invert: () => action.command.invert(before) }].slice(-HISTORY_CAP), future: [] },
      };
    }
    case 'undo': {
      const past = history.past;
      if (!past.length) return { state, history };
      const cmd = past[past.length - 1];
      const inverse = cmd.invert(state);
      return { state: inverse.apply(state), history: { past: past.slice(0, -1), future: [cmd, ...history.future] } };
    }
    case 'redo': {
      const future = history.future;
      if (!future.length) return { state, history };
      const cmd = future[0];
      const next = cmd.apply(state);
      return { state: next, history: { past: [...history.past, cmd], future: future.slice(1) } };
    }
    case 'select':
      return {
        state: { ...state, selection: { sceneId: action.sceneId, layerId: action.layerId ?? null, responseId: action.responseId ?? null } },
        history,
      };
    case 'camera':
      return { state: { ...state, camera: { x: action.x, y: action.y, zoom: action.zoom } }, history };
    case 'transport-time':
      return { state: { ...state, transport: { ...state.transport, time: action.time } }, history };
    case 'transport-play':
      return { state: { ...state, transport: { ...state.transport, playing: action.playing } }, history };
    case 'transport-loop':
      return { state: { ...state, transport: { ...state.transport, loopStart: action.start, loopEnd: action.end } }, history };
    case 'live-pin':
      return { state: { ...state, transport: { ...state.transport, pinnedSceneId: action.sceneId } }, history };
    case 'coach':
      return {
        state: { ...state, coach: { visible: action.visible ?? state.coach.visible, step: action.step ?? state.coach.step } },
        history,
      };
    case 'panels':
      return {
        state: { ...state, panels: { dockOpen: action.dockOpen ?? state.panels.dockOpen, inspectorOpen: action.inspectorOpen ?? state.panels.inspectorOpen, packageOpen: action.packageOpen ?? state.panels.packageOpen } },
        history,
      };
    case 'language':
      return { state: { ...state, language: action.language }, history };
    case 'webgl':
      return { state: { ...state, webglAvailable: action.available }, history };
    case 'save-state':
      return { state: { ...state, saveState: action.state }, history };
    case 'toast': {
      const toast: Toast = { id: `t-${state.toasts.length}-${Math.floor(action.text.length)}`, text: action.text };
      return { state: { ...state, toasts: [...state.toasts, toast].slice(-3) }, history };
    }
    case 'toast-expire':
      return { state: { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) }, history };
    case 'proposal':
      return { state: { ...state, proposal: action.proposal, proposalState: action.state }, history };
    default:
      return { state, history };
  }
}

const StoreContext = createContext<Store | null>(null);

interface EntryState {
  state: AppState;
  history: History;
}

function entryReducer(entry: EntryState, action: Action): EntryState {
  return reducer(entry.state, action, entry.history);
}

const initialEntry: EntryState = { state: initialAppState, history: { past: [], future: [] } };

export function StoreProvider({ children }: { children: ReactNode }) {
  const [entry, dispatch] = useReducer(entryReducer, initialEntry);
  const stateRef = useRef(entry.state);
  stateRef.current = entry.state;
  // dispatch/getState are identity-stable so consumers can hold them in effect
  // deps without tearing down subscriptions (the Pixi stage) on every dispatch.
  const stable = useMemo(() => ({ dispatch, getState: () => stateRef.current }), []);
  const store = useMemo<Store>(
    () => ({ ...stable, state: entry.state, history: entry.history }),
    [stable, entry.state, entry.history],
  );
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error('useStore outside StoreProvider');
  return store;
}

export function findScene(doc: DirectionDocument, sceneId: string | null) {
  return doc.scenes.find((s) => s.id === sceneId) ?? null;
}

export function findLayer(doc: DirectionDocument, sceneId: string | null, layerId: string | null): DirectionLayer | null {
  return doc.scenes.find((s) => s.id === sceneId)?.layers.find((l) => l.id === layerId) ?? null;
}

export function findResponse(doc: DirectionDocument, responseId: string | null): ResponseChain | null {
  for (const s of doc.scenes) {
    const r = s.responses.find((x) => x.id === responseId);
    if (r) return r;
  }
  return null;
}
