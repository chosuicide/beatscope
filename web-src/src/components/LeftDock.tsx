/**
 * Left dock: Scenes / Layers / Motion segmented control with a moving plate,
 * exactly as in the frozen frames (7 px radius, 34 px rows).
 */
import { useState } from 'react';
import { useStore } from '../app/store';
import { toggleLayerVisibleCommand, toggleLayerLockedCommand } from '../direction/commands';
import { translate } from '../app/i18n';
import { fmtTime } from '../render/board-renderer';
import { fitAllCamera } from '../demo/document';

type DockTab = 'scenes' | 'layers' | 'motion';

export function LeftDock() {
  const { state, dispatch } = useStore();
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);
  const [tab, setTab] = useState<DockTab>(() => {
    // deterministic view seeds (?docktab=layers) for tests/screenshots
    const q = new URLSearchParams(window.location.search);
    return q.get('docktab') === 'layers' ? 'layers' : q.get('docktab') === 'motion' ? 'motion' : 'scenes';
  });

  const scenes = [...state.doc.scenes].sort((a, b) => a.start_time - b.start_time);
  const selected = state.selection.sceneId
    ? state.doc.scenes.find((s) => s.id === state.selection.sceneId)
    : null;
  const liveScene = scenes.find(
    (s) => state.transport.time >= s.start_time && state.transport.time < s.end_time,
  );
  const selIndex = selected ? scenes.indexOf(selected) + 1 : 0;

  const selectScene = (id: string) => {
    dispatch({ type: 'select', sceneId: id, layerId: null, responseId: null });
    window.dispatchEvent(new CustomEvent('beathi:focus-scene', { detail: { sceneId: id } }));
    if (state.coach.visible && state.coach.step === 1) {
      dispatch({ type: 'coach', step: 2 });
    }
  };

  const totalDuration = fmtTime(scenes[scenes.length - 1]?.end_time ?? 0);

  return (
    <aside className={state.panels.dockOpen ? 'dock' : 'dock closed'}>
      {!state.panels.dockOpen && (
        <>
          <button
            className="ibtn"
            aria-label={t('dock.scenes')}
            onClick={() => dispatch({ type: 'panels', dockOpen: true })}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
              <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" />
              <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" />
              <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" />
              <rect x="9" y="9" width="4.5" height="4.5" rx="1" />
            </svg>
          </button>
          <button
            className="ibtn"
            aria-label="fit all"
            onClick={() => {
              const stage = document.querySelector('.stage');
              if (stage) {
                const fit = fitAllCamera(stage.clientWidth, stage.clientHeight, state.layout);
                dispatch({ type: 'camera', x: fit.x, y: fit.y, zoom: fit.zoom });
              }
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
              <path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4" />
            </svg>
          </button>
          <div className="rlab">{t('dock.scenes')}</div>
        </>
      )}
      {state.panels.dockOpen && (
        <>
          <div className="seg" role="tablist">
            <div
              className="seg-plate"
              style={{ transform: `translateX(${tab === 'scenes' ? 0 : tab === 'layers' ? 1 : 2} * 100%)` }}
            />
            {(['scenes', 'layers', 'motion'] as DockTab[]).map((k) => (
              <b key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)} role="tab" aria-selected={tab === k}>
                {t(`dock.${k}`)}
              </b>
            ))}
          </div>

          {tab === 'scenes' && (
            <>
              <div className="dcap">{t('dock.scenes.caption', { project: state.doc.project_title })}</div>
              {scenes.slice(0, 3).map((s, i) => (
                <div
                  key={s.id}
                  className={`drow${selected?.id === s.id ? ' on' : ''}`}
                  onClick={() => selectScene(s.id)}
                >
                  <span className="idx">{String(i + 1).padStart(2, '0')}</span>
                  <span className="nm">{s.title}</span>
                  {liveScene?.id === s.id && <span className="livek" />}
                  <span className="tm">
                    {fmtTime(s.start_time)}
                    {selected?.id === s.id ? `–${fmtTime(s.end_time)}` : ''}
                  </span>
                </div>
              ))}
              <div style={{ margin: '8px 8px 0' }}>
                <button className="btn-line dmore" style={{ width: '100%', color: 'var(--ink-1)' }} onClick={() => selectScene(scenes[3].id)}>
                  {t('dock.moreScenes', { count: scenes.length - 3 })}
                </button>
              </div>
              <div className="dfoot">
                {t('dock.footer.scenes', { count: scenes.length, duration: totalDuration })}
                {state.proposalState === 'pending' && state.proposal && (
                  <>
                    {' · '}
                    <button
                      className="dfoot-link"
                      onClick={() => dispatch({ type: 'panels', packageOpen: true, inspectorOpen: false })}
                    >
                      {t('dock.footer.proposal', { index: String(state.proposal.index).padStart(2, '0') })}
                    </button>
                  </>
                )}
              </div>
            </>
          )}

          {tab === 'layers' && selected && (
            <>
              <div className="dcap">{t('dock.layers.caption', { index: selIndex, title: selected.title })}</div>
              {selected.layers.map((l, i) => (
                <div
                  key={l.id}
                  className={`drow${state.selection.layerId === l.id ? ' on' : ''}`}
                  onClick={() =>
                    dispatch({ type: 'select', sceneId: selected.id, layerId: l.id, responseId: null })
                  }
                >
                  <span className="idx">{String(i + 1).padStart(2, '0')}</span>
                  <span className="nm" style={l.visible ? undefined : { opacity: 0.45 }}>
                    {l.label}
                  </span>
                  <button
                    className="ibtn"
                    aria-label={t('dock.aria.toggleVisible')}
                    style={{ opacity: l.visible ? 0.75 : 0.3 }}
                    onClick={(e) => {
                      e.stopPropagation();
                      dispatch({
                        type: 'command',
                        command: toggleLayerVisibleCommand(state.doc, selected.id, l.id),
                      });
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
                      <path d="M1.2 7C2.6 4.4 4.6 3 7 3s4.4 1.4 5.8 4C11.4 9.6 9.4 11 7 11S2.6 9.6 1.2 7Z" />
                      <circle cx="7" cy="7" r="1.7" />
                      {!l.visible && <path d="M2.4 11.6 11.6 2.4" />}
                    </svg>
                  </button>
                  <button
                    className="ibtn"
                    aria-label={t('dock.aria.toggleLock')}
                    style={{ opacity: l.locked ? 0.9 : 0.35 }}
                    onClick={(e) => {
                      e.stopPropagation();
                      dispatch({
                        type: 'command',
                        command: toggleLayerLockedCommand(state.doc, selected.id, l.id),
                      });
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
                      <rect x="3" y="6.2" width="8" height="5.6" rx="1.2" />
                      {l.locked ? (
                        <path d="M4.8 6.2V4.8a2.2 2.2 0 0 1 4.4 0v1.4" />
                      ) : (
                        <path d="M4.8 6.2V4.8a2.2 2.2 0 0 1 4.2-.9" />
                      )}
                    </svg>
                  </button>
                  <span className="tm">{l.kind}</span>
                </div>
              ))}
              <div className="dfoot">
                {t('dock.footer.layers', {
                  count: selected.layers.length,
                  hidden: selected.layers.filter((l) => !l.visible).length,
                })}
              </div>
            </>
          )}

          {tab === 'motion' && selected && (
            <>
              <div className="dcap">{t('dock.drivers')}</div>
              {selected.responses.map((r) => (
                <div
                  key={r.id}
                  className={`drow${state.selection.responseId === r.id ? ' on' : ''}`}
                  onClick={() =>
                    dispatch({
                      type: 'select',
                      sceneId: selected.id,
                      layerId: r.target_layer_id,
                      responseId: r.id,
                    })
                  }
                >
                  <span className="idx">{r.driver.kind === 'ranked_onsets' ? r.driver.band : r.driver.kind === 'beat_phase' ? 'beat' : 'energy'}</span>
                  <span className="nm">{r.label}</span>
                </div>
              ))}
            </>
          )}

          {(tab === 'layers' || tab === 'motion') && !selected && (
            <div className="dcap">{t(`dock.empty.${tab}`)}</div>
          )}
        </>
      )}
    </aside>
  );
}
