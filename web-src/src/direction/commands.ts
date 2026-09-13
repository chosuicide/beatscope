/**
 * Direction commands (plan §3.6): pure factories that turn one edit into
 * one undo transaction. `apply` returns the next editor state from the
 * state it is handed; `invert` rebuilds the pre-state from its closure —
 * the store pre-binds `invert` with the pre-apply state at commit time,
 * so inverses must never read the undo-time state.
 *
 * Structural edits (split, merge) restore the captured document wholesale;
 * parametric edits (move, rotate, scale, amount, crop) swap their from/to
 * arguments. Board drags produce move commands only — they never dispatch
 * transport actions, so dragging a board can never seek or restart audio.
 */
import type { AppState } from '../app/store';
import type {
  DirectionDocument,
  DirectionScene,
  DirectionLayer,
  ResponseChain,
  WorkspaceLayout,
  LayerCrop,
} from './types';
import { splitBoardBox, RATIO_SIZES } from './layout.js';

let cmdSeq = 0;
function cmdId(prefix: string): string {
  cmdSeq += 1;
  return `${prefix}-${cmdSeq}`;
}

export interface DirectionCommand {
  id: string;
  label: string;
  mergeKey?: string;
  apply(state: AppState): AppState;
  invert(before: AppState): DirectionCommand;
  affectedSceneIds: string[];
}

function cloneScenes(scenes: DirectionScene[]): DirectionScene[] {
  return scenes.map((s) => ({
    ...s,
    layers: s.layers.map((l) => ({ ...l })),
    responses: s.responses.map((r) => ({ ...r })),
  }));
}

function cloneDoc(doc: DirectionDocument): DirectionDocument {
  return { ...doc, composition: { ...doc.composition }, scenes: cloneScenes(doc.scenes) };
}

function cloneLayout(layout: WorkspaceLayout): WorkspaceLayout {
  return { boards: Object.fromEntries(Object.entries(layout.boards).map(([k, v]) => [k, { ...v }])) };
}

const round6 = (x: number) => Math.round(x * 1e6) / 1e6;

/* ------------------------------------------------------------------ */
/* Workspace commands (board boxes never touch the transport)          */

export function moveBoardCommand(sceneId: string, from: { x: number; y: number }, to: { x: number; y: number }): DirectionCommand {
  return {
    id: cmdId('move'),
    label: 'Move board',
    mergeKey: `move-board:${sceneId}`,
    affectedSceneIds: [sceneId],
    apply(state) {
      const layout = cloneLayout(state.layout);
      const box = layout.boards[sceneId];
      if (box) {
        box.x = to.x;
        box.y = to.y;
      }
      return { ...state, layout, saveState: 'offline' };
    },
    invert() {
      return moveBoardCommand(sceneId, to, from);
    },
  };
}

export function rotateBoardCommand(sceneId: string, from: number, to: number): DirectionCommand {
  return {
    id: cmdId('rot'),
    label: 'Rotate board',
    affectedSceneIds: [sceneId],
    apply(state) {
      const layout = cloneLayout(state.layout);
      const box = layout.boards[sceneId];
      if (box) box.rotation = to;
      return { ...state, layout, saveState: 'offline' };
    },
    invert() {
      return rotateBoardCommand(sceneId, to, from);
    },
  };
}

export function scaleBoardCommand(
  sceneId: string,
  from: { w: number; bodyH: number },
  to: { w: number; bodyH: number },
): DirectionCommand {
  return {
    id: cmdId('scale'),
    label: 'Scale board',
    mergeKey: `scale-board:${sceneId}`,
    affectedSceneIds: [sceneId],
    apply(state) {
      const layout = cloneLayout(state.layout);
      const box = layout.boards[sceneId];
      if (box) {
        box.w = to.w;
        box.bodyH = to.bodyH;
      }
      return { ...state, layout, saveState: 'offline' };
    },
    invert() {
      return scaleBoardCommand(sceneId, to, from);
    },
  };
}

/* ------------------------------------------------------------------ */
/* Layer commands                                                      */

export function setLayerCropCommand(
  doc: DirectionDocument,
  sceneId: string,
  layerId: string,
  to: LayerCrop | undefined,
): DirectionCommand {
  const before = doc.scenes.find((s) => s.id === sceneId)?.layers.find((l) => l.id === layerId)?.transform.crop;
  const from: LayerCrop | undefined = before ? { ...before } : undefined;
  return {
    id: cmdId('crop'),
    label: 'Set layer crop',
    mergeKey: `crop:${layerId}`,
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const layer = doc2.scenes.find((s) => s.id === sceneId)?.layers.find((l) => l.id === layerId);
      if (layer) layer.transform = { ...layer.transform, crop: to ? { ...to } : undefined };
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return setLayerCropCommand(doc, sceneId, layerId, from);
    },
  };
}

export function setLayerSourceCommand(
  doc: DirectionDocument,
  sceneId: string,
  layerId: string,
  to: string,
): DirectionCommand {
  const before = doc.scenes.find((s) => s.id === sceneId)?.layers.find((l) => l.id === layerId)?.props as
    | Record<string, unknown>
    | undefined;
  const from = typeof before?.src === 'string' ? before.src : '';
  return {
    id: cmdId('src'),
    label: 'Set layer source',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const layer = doc2.scenes.find((s) => s.id === sceneId)?.layers.find((l) => l.id === layerId);
      if (layer) layer.props = { ...layer.props, src: to };
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return setLayerSourceCommand(doc, sceneId, layerId, from);
    },
  };
}

/**
 * Detach every reference to a deleted project asset as one history entry.
 * The tombstone source preserves the content id for diagnosis/replacement,
 * while no longer claiming the bytes still exist in the project manifest.
 */
export function markAssetMissingCommand(doc: DirectionDocument, assetId: string): DirectionCommand {
  const from = `asset:${assetId}`;
  const to = `missing-asset:${assetId}`;
  const affected = doc.scenes
    .filter((scene) => scene.layers.some((layer) => (layer.props as Record<string, unknown>).src === from))
    .map((scene) => scene.id);
  return {
    id: cmdId('asset-missing'),
    label: 'Mark deleted asset missing',
    affectedSceneIds: affected,
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      for (const scene of doc2.scenes) {
        for (const layer of scene.layers) {
          const props = layer.props as Record<string, unknown>;
          if (props.src === from) layer.props = { ...props, src: to };
        }
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return {
        id: cmdId('asset-restore-ref'),
        label: 'Restore deleted asset references',
        affectedSceneIds: affected,
        apply(state) {
          const doc2 = cloneDoc(state.doc);
          for (const scene of doc2.scenes) {
            for (const layer of scene.layers) {
              const props = layer.props as Record<string, unknown>;
              if (props.src === to) layer.props = { ...props, src: from };
            }
          }
          return { ...state, doc: doc2, saveState: 'offline' };
        },
        invert: () => markAssetMissingCommand(doc, assetId),
      };
    },
  };
}

export function toggleLayerVisibleCommand(doc: DirectionDocument, sceneId: string, layerId: string): DirectionCommand {
  return {
    id: cmdId('vis'),
    label: 'Toggle layer visibility',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      for (const s of doc2.scenes) {
        if (s.id !== sceneId) continue;
        for (const l of s.layers) {
          if (l.id === layerId) l.visible = !l.visible;
        }
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return toggleLayerVisibleCommand(doc, sceneId, layerId);
    },
  };
}

export function toggleLayerLockedCommand(doc: DirectionDocument, sceneId: string, layerId: string): DirectionCommand {
  return {
    id: cmdId('lock'),
    label: 'Toggle layer lock',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      for (const s of doc2.scenes) {
        if (s.id !== sceneId) continue;
        for (const l of s.layers) {
          if (l.id === layerId) l.locked = !l.locked;
        }
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return toggleLayerLockedCommand(doc, sceneId, layerId);
    },
  };
}

/* ------------------------------------------------------------------ */
/* Scene structure commands                                            */

export function setResponseAmountCommand(doc: DirectionDocument, responseId: string, from: number, to: number): DirectionCommand {
  const scene = doc.scenes.find((s) => s.responses.some((r) => r.id === responseId));
  return {
    id: cmdId('amt'),
    label: 'Change response amount',
    mergeKey: `amount:${responseId}`,
    affectedSceneIds: scene ? [scene.id] : [],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      for (const s of doc2.scenes) {
        for (const r of s.responses) {
          if (r.id === responseId && 'amount' in r.motion) {
            (r.motion as { amount: number }).amount = to;
          }
        }
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return setResponseAmountCommand(doc, responseId, to, from);
    },
  };
}

export function addResponseCommand(doc: DirectionDocument, sceneId: string, response: ResponseChain): DirectionCommand {
  const chain: ResponseChain = {
    ...response,
    driver: { ...response.driver } as ResponseChain['driver'],
    motion: { ...response.motion } as ResponseChain['motion'],
  };
  return {
    id: cmdId('add-response'),
    label: 'Add response chain',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const scene = doc2.scenes.find((s) => s.id === sceneId);
      if (scene) scene.responses.push({ ...chain, driver: { ...chain.driver } as ResponseChain['driver'], motion: { ...chain.motion } as ResponseChain['motion'] });
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return removeResponseCommand(doc, sceneId, chain.id);
    },
  };
}

export function removeResponseCommand(doc: DirectionDocument, sceneId: string, responseId: string): DirectionCommand {
  const scene = doc.scenes.find((s) => s.id === sceneId);
  const index = scene ? scene.responses.findIndex((r) => r.id === responseId) : -1;
  const removed = index >= 0 ? scene!.responses[index] : null;
  return {
    id: cmdId('remove-response'),
    label: 'Remove response chain',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const target = doc2.scenes.find((s) => s.id === sceneId);
      if (target) target.responses = target.responses.filter((r) => r.id !== responseId);
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      if (!removed) return removeResponseCommand(doc, sceneId, responseId);
      return insertResponseCommand(doc, sceneId, removed, index);
    },
  };
}

/** Re-insert a captured chain at its original position (undo of remove). */
export function insertResponseCommand(
  doc: DirectionDocument,
  sceneId: string,
  response: ResponseChain,
  index: number,
): DirectionCommand {
  return {
    id: cmdId('insert-response'),
    label: 'Restore response chain',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const scene = doc2.scenes.find((s) => s.id === sceneId);
      if (scene && !scene.responses.some((r) => r.id === response.id)) {
        scene.responses.splice(Math.max(0, Math.min(index, scene.responses.length)), 0, {
          ...response,
          driver: { ...response.driver } as ResponseChain['driver'],
          motion: { ...response.motion } as ResponseChain['motion'],
        });
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return removeResponseCommand(doc, sceneId, response.id);
    },
  };
}

export function setResponseDriverCommand(
  doc: DirectionDocument,
  sceneId: string,
  responseId: string,
  to: ResponseChain['driver'],
): DirectionCommand {
  const before = doc.scenes
    .find((s) => s.id === sceneId)
    ?.responses.find((r) => r.id === responseId)?.driver;
  const from = before ? ({ ...before } as ResponseChain['driver']) : null;
  return {
    id: cmdId('response-driver'),
    label: 'Change response driver',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const chain = doc2.scenes.find((s) => s.id === sceneId)?.responses.find((r) => r.id === responseId);
      // changing driver density never rewrites the motion (§5.3)
      if (chain) chain.driver = { ...to } as ResponseChain['driver'];
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return from ? setResponseDriverCommand(doc, sceneId, responseId, from) : removeResponseCommand(doc, sceneId, responseId);
    },
  };
}

export function setResponseMotionCommand(
  doc: DirectionDocument,
  sceneId: string,
  responseId: string,
  to: ResponseChain['motion'],
): DirectionCommand {
  const before = doc.scenes
    .find((s) => s.id === sceneId)
    ?.responses.find((r) => r.id === responseId)?.motion;
  const from = before ? ({ ...before } as ResponseChain['motion']) : null;
  return {
    id: cmdId('response-motion'),
    label: 'Change response motion',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const chain = doc2.scenes.find((s) => s.id === sceneId)?.responses.find((r) => r.id === responseId);
      // changing the motion never rewrites evidence selection (§5.3)
      if (chain) chain.motion = { ...to } as ResponseChain['motion'];
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return from ? setResponseMotionCommand(doc, sceneId, responseId, from) : removeResponseCommand(doc, sceneId, responseId);
    },
  };
}

export function assignResponseLayerCommand(
  doc: DirectionDocument,
  sceneId: string,
  responseId: string,
  layerId: string,
): DirectionCommand {
  const before = doc.scenes
    .find((s) => s.id === sceneId)
    ?.responses.find((r) => r.id === responseId)?.target_layer_id;
  const from = before ?? null;
  return {
    id: cmdId('response-layer'),
    label: 'Assign response chain',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const scene = doc2.scenes.find((s) => s.id === sceneId);
      const chain = scene?.responses.find((r) => r.id === responseId);
      if (scene && chain && scene.layers.some((l) => l.id === layerId)) {
        chain.target_layer_id = layerId;
      }
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return from ? assignResponseLayerCommand(doc, sceneId, responseId, from) : removeResponseCommand(doc, sceneId, responseId);
    },
  };
}

export function renameSceneCommand(doc: DirectionDocument, sceneId: string, from: string, to: string): DirectionCommand {
  return {
    id: cmdId('rename'),
    label: 'Rename scene',
    affectedSceneIds: [sceneId],
    apply(state) {
      const doc2 = cloneDoc(state.doc);
      const scene = doc2.scenes.find((s) => s.id === sceneId);
      if (scene) scene.title = to;
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return renameSceneCommand(doc, sceneId, to, from);
    },
  };
}

/** Where to cut a scene; omitted, the anchor midpoint is used. */
export type SplitSpec = { kind: 'bars'; bar: number } | { kind: 'time'; second: number };

/**
 * Split one scene into two consecutive halves at a bar (or exact second).
 * The first half takes the hard `cut`; the second keeps the original
 * transition out. Layers and responses are duplicated into both halves
 * (the second copy carries a `-b` id suffix), so coverage and layer
 * bindings stay continuous without touching source structure facts.
 */
export function splitSceneCommand(
  doc: DirectionDocument,
  sceneId: string,
  layout: WorkspaceLayout,
  spec?: SplitSpec,
  barBoundaryTimes?: Record<number, number>,
): DirectionCommand {
  const requestedId = `${sceneId}-b`;
  return {
    id: cmdId('split'),
    label: 'Split scene',
    affectedSceneIds: [sceneId, requestedId],
    apply(state) {
      const idx = state.doc.scenes.findIndex((s) => s.id === sceneId);
      if (idx < 0) return state;
      const scene = state.doc.scenes[idx];
      const usedSceneIds = new Set(state.doc.scenes.map((s) => s.id));
      let newId = requestedId;
      while (usedSceneIds.has(newId)) newId = `${newId}-b`;
      const anchor = scene.anchor;
      let midBar = 0;
      let midTime = 0;
      if (anchor.kind === 'bars') {
        midBar = spec?.kind === 'bars' ? spec.bar : anchor.start_bar + Math.ceil((anchor.end_bar - anchor.start_bar) / 2);
        if (!(anchor.start_bar < midBar && midBar < anchor.end_bar)) return state;
        const t = barBoundaryTimes?.[midBar];
        if (typeof t !== 'number' || !Number.isFinite(t)) return state;
        midTime = round6(t);
        if (!(scene.start_time < midTime && midTime < scene.end_time)) return state;
      } else {
        midTime = round6(spec?.kind === 'time' ? spec.second : (anchor.start_seconds + anchor.end_seconds) / 2);
        if (!(anchor.start_seconds < midTime && midTime < anchor.end_seconds)) return state;
      }

      const sceneA: DirectionScene =
        anchor.kind === 'bars'
          ? { ...scene, anchor: { kind: 'bars', start_bar: anchor.start_bar, end_bar: midBar }, end_time: midTime, transition_out: 'cut' }
          : { ...scene, anchor: { kind: 'time', start_seconds: anchor.start_seconds, end_seconds: midTime }, end_time: midTime, transition_out: 'cut' };
      const sceneB: DirectionScene = {
        ...scene,
        id: newId,
        title: `${scene.title} B`,
        anchor:
          anchor.kind === 'bars'
            ? { kind: 'bars', start_bar: midBar, end_bar: anchor.end_bar }
            : { kind: 'time', start_seconds: midTime, end_seconds: anchor.end_seconds },
        start_time: midTime,
        layers: scene.layers.map(
          (l): DirectionLayer => ({
            ...l,
            id: `${l.id}-b`,
            transform: { ...l.transform, crop: l.transform.crop ? { ...l.transform.crop } : undefined },
          }),
        ),
        responses: scene.responses.map((r) => ({ ...r, id: `${r.id}-b`, target_layer_id: `${r.target_layer_id}-b` })),
      };

      const scenes = [...state.doc.scenes];
      scenes.splice(idx, 1, sceneA, sceneB);
      const layout2 = cloneLayout(state.layout);
      const box = layout2.boards[sceneId];
      if (box) layout2.boards[newId] = splitBoardBox(box);
      return {
        ...state,
        doc: { ...state.doc, scenes },
        layout: layout2,
        saveState: 'offline',
      };
    },
    invert() {
      return restoreDocumentCommand(doc, layout, 'Split scene');
    },
  };
}

/**
 * Merge a scene into its chronological predecessor (never reordered in
 * musical time). The merged scene spans both anchors, keeps the
 * predecessor's identity, and inherits the merged-away scene's transition
 * out. Colliding layer/response ids gain an `-m` suffix deterministically.
 */
export function mergeSceneCommand(
  doc: DirectionDocument,
  sceneId: string,
  layout: WorkspaceLayout,
): DirectionCommand {
  return {
    id: cmdId('merge'),
    label: 'Merge scene',
    affectedSceneIds: [],
    apply(state) {
      const idx = state.doc.scenes.findIndex((s) => s.id === sceneId);
      if (idx < 1) return state;
      const scenes = [...state.doc.scenes];
      const prev = scenes[idx - 1];
      const cur = scenes[idx];
      const anchor =
        prev.anchor.kind === 'bars' && cur.anchor.kind === 'bars'
          ? { kind: 'bars' as const, start_bar: prev.anchor.start_bar, end_bar: cur.anchor.end_bar }
          : { kind: 'time' as const, start_seconds: prev.start_time, end_seconds: cur.end_time };

      const usedLayerIds = new Set(prev.layers.map((l) => l.id));
      const layerRemap = new Map<string, string>();
      const mergedLayers = [
        ...prev.layers,
        ...cur.layers.map((l) => {
          let id = `${cur.id}-${l.id}`;
          while (usedLayerIds.has(id)) id = `${id}-m`;
          usedLayerIds.add(id);
          layerRemap.set(l.id, id);
          return { ...l, id };
        }),
      ];
      const usedResponseIds = new Set(prev.responses.map((r) => r.id));
      const mergedResponses = [
        ...prev.responses,
        ...cur.responses.map((r) => {
          let id = `${cur.id}-${r.id}`;
          while (usedResponseIds.has(id)) id = `${id}-m`;
          usedResponseIds.add(id);
          return { ...r, id, target_layer_id: layerRemap.get(r.target_layer_id) ?? r.target_layer_id };
        }),
      ];

      const merged: DirectionScene = {
        ...prev,
        anchor,
        start_time: prev.start_time,
        end_time: cur.end_time,
        transition_out: cur.transition_out,
        layers: mergedLayers,
        responses: mergedResponses,
      };
      scenes.splice(idx - 1, 2, merged);
      const layout2 = cloneLayout(state.layout);
      delete layout2.boards[cur.id];
      return {
        ...state,
        doc: { ...state.doc, scenes },
        layout: layout2,
        saveState: 'offline',
      };
    },
    invert() {
      return restoreDocumentCommand(doc, layout, 'Merge scene');
    },
  };
}

/** Composition ratio switch; normalized layer geometry stays untouched. */
export function setPrimaryRatioCommand(
  doc: DirectionDocument,
  ratio: '16:9' | '9:16' | '1:1',
): DirectionCommand {
  const from = doc.composition.primary_ratio;
  return {
    id: cmdId('ratio'),
    label: 'Switch composition ratio',
    affectedSceneIds: [],
    apply(state) {
      const size = RATIO_SIZES[ratio];
      const doc2 = cloneDoc(state.doc);
      doc2.composition = { ...doc2.composition, primary_ratio: ratio, width: size.width, height: size.height };
      return { ...state, doc: doc2, saveState: 'offline' };
    },
    invert() {
      return setPrimaryRatioCommand(doc, from);
    },
  };
}

/* ------------------------------------------------------------------ */
/* Composite & restore                                                 */

/** Agent Apply wraps all accepted operations in one composite command (§3.6). */
export function compositeCommand(label: string, parts: DirectionCommand[]): DirectionCommand {
  return {
    id: cmdId('composite'),
    label,
    affectedSceneIds: [...new Set(parts.flatMap((p) => p.affectedSceneIds))],
    apply(state) {
      return parts.reduce((acc, p) => p.apply(acc), state);
    },
    invert(before) {
      // Replay the composite to find each part's own pre-state, then invert
      // the parts in reverse order. Parametric parts ignore the passed state
      // (their inverses are closure-bound); structural parts restore the
      // document captured at construction, which subsumes earlier parts.
      const states: AppState[] = [before];
      for (let i = 0; i + 1 < parts.length; i++) states.push(parts[i].apply(states[i]));
      const inverses = parts.map((p, i) => p.invert(states[i]));
      return compositeCommand(label, inverses.reverse());
    },
  };
}

/**
 * Whole-document restore used as the inverse of structural commands. Its
 * own inverse is a self-restore: restore commands never enter history
 * directly, they are only produced when the store unwinds a structural
 * command.
 */
export function restoreDocumentCommand(doc: DirectionDocument, layout: WorkspaceLayout, label: string): DirectionCommand {
  return {
    id: cmdId('restore'),
    label,
    affectedSceneIds: doc.scenes.map((s) => s.id),
    apply(state) {
      return { ...state, doc: cloneDoc(doc), layout: cloneLayout(layout), saveState: 'offline' };
    },
    invert() {
      return restoreDocumentCommand(doc, layout, label);
    },
  };
}
