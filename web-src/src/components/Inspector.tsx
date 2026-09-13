/**
 * Right inspector (frozen frame C): crumb, Transform / Crop / Responses /
 * Transition sections. All edits go through direction commands so every
 * change is one undo transaction.
 *
 * Round 2 Commit 2 adds: scene rename (commit on blur), the Board section
 * (rotation / scale / split / merge — scene selected without a layer),
 * a functional Reset crop, and the composition + history card shown when
 * nothing is selected. The frozen layer-selected view is unchanged.
 */
import { useRef, useState } from 'react';
import { useStore } from '../app/store';
import { setResponseAmountCommand } from '../app/store';
import {
  rotateBoardCommand,
  scaleBoardCommand,
  setLayerCropCommand,
  splitSceneCommand,
  mergeSceneCommand,
  renameSceneCommand,
  setPrimaryRatioCommand,
} from '../direction/commands';
import { translate } from '../app/i18n';
import type { ResponseChain, DirectionLayer } from '../direction/types';

const TIER: Record<string, string> = { primary: 'T1', secondary: 'T2', tertiary: 'T3' };

const OPERATOR: Record<string, string> = {
  scale_pulse: 'scale-pulse',
  translate_recoil: 'translate-plate',
  opacity_lift: 'opacity-lift',
};

const RATIOS = ['16:9', '9:16', '1:1'] as const;

function layerTransformRows(layer: DirectionLayer): Array<[string, string]> {
  const p = layer.props as Record<string, unknown>;
  const rect = p.rect as { x: number; y: number; w: number; h: number } | undefined;
  if (rect) {
    const bodyW = 220;
    const bodyH = 127;
    return [
      ['X', `${Math.round(rect.x * bodyW)} px`],
      ['Y', `${Math.round(rect.y * bodyH)} px`],
      ['Size', `${Math.round(rect.w * bodyW)} px · ${Math.round((rect.h ?? 1) * bodyH)} px`],
      ['Rotation', `${layer.transform.rotation.toFixed(1)}°`],
    ];
  }
  if (p.pos) {
    const [x, y] = p.pos as [number, number];
    return [
      ['X', `${x} px`],
      ['Y', `${y} px`],
      ['Rotation', `${layer.transform.rotation.toFixed(1)}°`],
    ];
  }
  return [['Rotation', `${layer.transform.rotation.toFixed(1)}°`]];
}

function cropRows(layer: DirectionLayer): Array<[string, string]> | null {
  const crop = layer.transform.crop;
  if (crop) {
    const pct = (v: number) => `${Math.round(v * 1000) / 10}%`;
    return [
      ['Left / Right', `${pct(crop.left)} · ${pct(1 - crop.right)}`],
      ['Top / Bottom', `${pct(crop.top)} · ${pct(1 - crop.bottom)}`],
    ];
  }
  const p = layer.props as Record<string, unknown>;
  const rect = p.rect as { x?: number; y?: number; w?: number; h?: number } | undefined;
  if (p.torn && rect?.w != null) {
    const cropPct = Math.round((1 - rect.w) * 1000) / 10;
    return [
      ['Left / Right', `${p.torn === 'left' ? cropPct : 0}% · ${p.torn === 'left' ? 0 : cropPct}%`],
      ['Top / Bottom', '0% · 0%'],
    ];
  }
  if (rect?.x != null && rect.w != null && rect.w <= 1) {
    return [
      ['Left / Right', `${Math.round(rect.x * 1000) / 10}% · ${Math.round((1 - rect.x - rect.w) * 1000) / 10}%`],
      ['Top / Bottom', `${Math.round((rect.y ?? 0) * 1000) / 10}% · ${Math.round((1 - (rect.y ?? 0) - (rect.h ?? 1)) * 1000) / 10}%`],
    ];
  }
  return null;
}

function triggerChips(r: ResponseChain): Array<{ label: string; acc: boolean }> {
  const d = r.driver;
  if (d.kind === 'ranked_onsets') {
    return [
      { label: 'onset', acc: true },
      { label: `band ${d.band}`, acc: false },
      { label: TIER[d.tier] ?? 'T1', acc: false },
    ];
  }
  if (d.kind === 'beat_phase') {
    return [
      { label: 'beat', acc: true },
      { label: `subdivision ${d.subdivision}`, acc: false },
    ];
  }
  return [
    { label: 'energy', acc: true },
    { label: `band ${d.band}`, acc: false },
  ];
}

export function Inspector() {
  const { state, dispatch, history } = useStore();
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);
  const scaleBaseRef = useRef<{ w: number; bodyH: number } | null>(null);
  const [titleDraft, setTitleDraft] = useState<string | null>(null);

  if (!state.panels.inspectorOpen || state.panels.packageOpen) return null;

  const scene = state.selection.sceneId
    ? state.doc.scenes.find((s) => s.id === state.selection.sceneId)
    : null;
  const sceneIndex = scene ? state.doc.scenes.indexOf(scene) + 1 : null;
  const layer =
    scene && state.selection.layerId
      ? scene.layers.find((l) => l.id === state.selection.layerId)
      : null;
  const response =
    scene && state.selection.responseId
      ? scene.responses.find((r) => r.id === state.selection.responseId)
      : null;

  if (!scene) {
    return (
      <aside className="insp">
        <div className="icrumb">{state.doc.project_title}</div>
        <div className="ihead">
          <h2>{t('inspector.crumb', { project: state.doc.project_title, index: '—', layer: '—' })}</h2>
        </div>
        <p className="note" style={{ padding: '12px 16px' }}>
          {t('inspector.empty.noSelection')}
        </p>
        <div className="isec">
          <h3>{t('inspector.section.composition')}</h3>
          <div className="irow">
            <span className="ilab">{t('inspector.label.ratio')}</span>
            <div className="stack" style={{ flex: 1 }}>
              {RATIOS.map((r) => (
                <button
                  key={r}
                  className={`chip${state.doc.composition.primary_ratio === r ? ' acc' : ''}`}
                  onClick={() =>
                    dispatch({ type: 'command', command: setPrimaryRatioCommand(state.doc, r) })
                  }
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
          <div className="irow">
            <span className="ilab">Canvas</span>
            <span className="iin">{`${state.doc.composition.width} × ${state.doc.composition.height}`}</span>
          </div>
        </div>
        <div className="isec">
          <h3>{t('inspector.section.history')}</h3>
          <div className="trow2">
            <button
              className="tbtn"
              disabled={history.past.length === 0}
              style={{ opacity: history.past.length === 0 ? 0.4 : 1 }}
              onClick={() => dispatch({ type: 'undo' })}
            >
              {t('inspector.action.undo')}
            </button>
            <button
              className="tbtn"
              disabled={history.future.length === 0}
              style={{ opacity: history.future.length === 0 ? 0.4 : 1 }}
              onClick={() => dispatch({ type: 'redo' })}
            >
              {t('inspector.action.redo')}
            </button>
          </div>
        </div>
      </aside>
    );
  }

  const box = state.layout.boards[scene.id];
  const sceneIdxInDoc = state.doc.scenes.indexOf(scene);
  const canSplit =
    scene.anchor.kind === 'bars'
      ? scene.anchor.end_bar - scene.anchor.start_bar >= 2
      : scene.end_time - scene.start_time >= 1;
  const canMerge = sceneIdxInDoc > 0;

  const commitTitle = () => {
    if (titleDraft !== null && titleDraft.trim() && titleDraft.trim() !== scene.title) {
      dispatch({
        type: 'command',
        command: renameSceneCommand(state.doc, scene.id, scene.title, titleDraft.trim()),
      });
    }
    setTitleDraft(null);
  };

  return (
    <aside className="insp">
      <div className="icrumb">
        {state.doc.project_title} / Scene {sceneIndex}
        {layer ? ` / ${layer.label}` : ''}
      </div>
      <div className="ihead">
        {layer ? (
          <h2>{layer.label}</h2>
        ) : (
          <input
            key={scene.id}
            className="title-edit"
            value={titleDraft ?? scene.title}
            aria-label={t('inspector.section.board')}
            onChange={(e) => setTitleDraft(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
          />
        )}
        <span className="kchip">{layer ? layer.kind : scene.family}</span>
      </div>

      {!layer && box && (
        <div className="isec">
          <h3>{t('inspector.section.board')}</h3>
          <div className="irow">
            <span className="ilab">{t('inspector.label.rotation')}</span>
            <div className="stack" style={{ flex: 1 }}>
              <input
                type="range"
                className="amt"
                min={-15}
                max={15}
                step={0.1}
                value={box.rotation}
                onChange={(e) =>
                  dispatch({
                    type: 'command',
                    command: rotateBoardCommand(scene.id, box.rotation, Number(e.target.value)),
                  })
                }
              />
              <span className="iin">{`${box.rotation.toFixed(1)}°`}</span>
            </div>
          </div>
          <div className="irow">
            <span className="ilab">{t('inspector.label.scale')}</span>
            <div className="stack" style={{ flex: 1 }}>
              <input
                type="range"
                className="amt"
                min={0.5}
                max={1.5}
                step={0.05}
                value={scaleBaseRef.current ? box.w / scaleBaseRef.current.w : 1}
                onPointerDown={() => {
                  scaleBaseRef.current = { w: box.w, bodyH: box.bodyH };
                }}
                onChange={(e) => {
                  const base = scaleBaseRef.current ?? { w: box.w, bodyH: box.bodyH };
                  const k = Number(e.target.value);
                  dispatch({
                    type: 'command',
                    command: scaleBoardCommand(scene.id, { w: box.w, bodyH: box.bodyH }, { w: base.w * k, bodyH: base.bodyH * k }),
                  });
                }}
              />
              <span className="iin">{`${Math.round((scaleBaseRef.current ? box.w / scaleBaseRef.current.w : 1) * 100)}%`}</span>
            </div>
          </div>
          <div className="irow">
            <span className="ilab">{t('inspector.label.duration')}</span>
            <span className="iin">{`${Math.round(scene.end_time - scene.start_time)} s`}</span>
          </div>
          <div className="trow2" style={{ marginTop: 8 }}>
            <button
              className="tbtn"
              style={{ color: 'var(--accent)' }}
              disabled={!canSplit}
              title={canSplit ? undefined : t('inspector.hint.splitDisabled')}
              onClick={() =>
                dispatch({
                  type: 'command',
                  command: splitSceneCommand(
                    state.doc,
                    scene.id,
                    state.layout,
                    undefined,
                    Object.fromEntries(state.rhythm.beats.filter((b) => b.beat === 1).map((b) => [b.bar, b.time])),
                  ),
                })
              }
            >
              {t('inspector.action.split')}
            </button>
            <button
              className="tbtn"
              disabled={!canMerge}
              style={{ opacity: canMerge ? 1 : 0.4 }}
              onClick={() =>
                dispatch({
                  type: 'command',
                  command: mergeSceneCommand(state.doc, scene.id, state.layout),
                })
              }
            >
              {t('inspector.action.merge')}
            </button>
          </div>
        </div>
      )}

      {layer && (
        <div className="isec">
          <h3>{t('inspector.section.transform')}</h3>
          {layerTransformRows(layer).map(([lab, val]) => (
            <div className="irow" key={lab}>
              <span className="ilab">{lab}</span>
              <span className="iin">{val}</span>
            </div>
          ))}
        </div>
      )}

      {layer && cropRows(layer) && (
        <div className="isec">
          <h3>{t('inspector.section.crop')}</h3>
          {cropRows(layer)!.map(([lab, val]) => (
            <div className="irow" key={lab}>
              <span className="ilab">{lab}</span>
              <div className="i2">
                {val.split(' · ').map((v) => (
                  <span className="iin" key={v}>
                    {v}
                  </span>
                ))}
              </div>
            </div>
          ))}
          <div className="trow2" style={{ marginTop: 8 }}>
            <button
              className="tbtn"
              style={{ color: 'var(--accent)' }}
              onClick={() =>
                dispatch({
                  type: 'command',
                  command: setLayerCropCommand(state.doc, scene.id, layer.id, undefined),
                })
              }
            >
              {t('inspector.action.resetCrop')}
            </button>
            <span className="note" style={{ marginLeft: 'auto' }}>
              {t('inspector.note.deterministicSeek')}
            </span>
          </div>
        </div>
      )}

      <div className="isec">
        <h3>{t('inspector.section.responses')}</h3>
        {scene.responses.map((r) => {
          const open = response?.id === r.id;
          const unavailable = Boolean(r.unavailable_reason);
          const tier = r.driver.kind === 'ranked_onsets' ? TIER[r.driver.tier] : '—';
          return (
            <div key={r.id}>
              <div
                className={`resrow${open ? ' on' : ''}`}
                onClick={() =>
                  dispatch({
                    type: 'select',
                    sceneId: scene.id,
                    layerId: r.target_layer_id,
                    responseId: open ? null : r.id,
                  })
                }
              >
                <svg className="chev" width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.4">
                  {open ? <path d="M7 1.5 3 5 7 8.5" /> : <path d="M3 1.5 7 5 3 8.5" />}
                </svg>
                <span className="rt">{r.label}</span>
                <span className={`chip${unavailable ? ' off' : ''}`}>{unavailable ? 'n/a' : tier}</span>
              </div>
              {open && (
                <div className="rdet">
                  <div className="irow">
                    <span className="ilab">{t('inspector.label.trigger')}</span>
                    <div className="stack">
                      {triggerChips(r).map((c) => (
                        <span key={c.label} className={`chip${c.acc ? ' acc' : ''}`}>
                          {c.label}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="irow">
                    <span className="ilab">{t('inspector.label.operator')}</span>
                    <span className="iin">{OPERATOR[r.motion.kind]}</span>
                  </div>
                  {!unavailable && (
                    <div className="irow">
                      <span className="ilab">{t('inspector.label.amount')}</span>
                      <div className="stack" style={{ flex: 1 }}>
                        <input
                          type="range"
                          className="amt"
                          min={0}
                          max={0.12}
                          step={0.005}
                          value={r.motion.amount}
                          onChange={(e) => {
                            const amount = Number(e.target.value);
                            dispatch({
                              type: 'command',
                              command: setResponseAmountCommand(state.doc, r.id, r.motion.amount, amount),
                            });
                            if (state.coach.visible && state.coach.step === 2) {
                              dispatch({ type: 'coach', step: 3 });
                            }
                          }}
                        />
                        <span className="iin">{`${Math.round(r.motion.amount * 100)}%`}</span>
                      </div>
                    </div>
                  )}
                  <div className="irow">
                    <span className="ilab">{t('inspector.label.duration')}</span>
                    <span className="iin">{`${Math.round((r.motion.attack_seconds + r.motion.release_seconds) * 1000)} ms`}</span>
                  </div>
                  <div className="irow">
                    <span className="ilab">{t('inspector.label.combine')}</span>
                    <span className="iin">max</span>
                  </div>
                  {unavailable ? (
                    <p className="note" style={{ marginTop: 8 }}>
                      {r.unavailable_reason}
                    </p>
                  ) : (
                    r.driver.kind === 'ranked_onsets' && (
                      <p className="note" style={{ marginTop: 8 }}>
                        {t('inspector.note.budget', {
                          n: r.driver.max_events_per_bar,
                          free: Math.max(0, r.driver.max_events_per_bar - 1),
                          bar: scene.anchor.kind === 'bars' ? scene.anchor.end_bar - 1 : '—',
                        })}
                      </p>
                    )
                  )}
                </div>
              )}
            </div>
          );
        })}
        {scene.responses.length === 0 && (
          <p className="note">{t('dock.empty.motion')}</p>
        )}
      </div>

      <div className="isec">
        <h3>{t('inspector.section.transition')}</h3>
        <div className="irow">
          <span className="ilab">{t('inspector.label.curve')}</span>
          <span className="iin" style={{ fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 520 }}>
            {scene.transition_out === 'directional-wipe' ? 'wipe' : scene.transition_out === 'hold-through' ? 'hold' : scene.transition_out}
          </span>
        </div>
        <div className="irow">
          <span className="ilab">{t('inspector.label.duration')}</span>
          <span className="iin">240 ms</span>
        </div>
      </div>
    </aside>
  );
}
