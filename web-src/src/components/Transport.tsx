/**
 * Floating transport (frozen frames): play, timeline with fill + knob,
 * time with one decimal, bar·beat, scene name, loop, zoom %.
 */
import { useStore } from '../app/store';
import { translate } from '../app/i18n';
import type { DemoRhythm } from '../demo/rhythm';

function timeLabel(t: number): string {
  const m = Math.floor(t / 60);
  const s = t % 60;
  const whole = Math.floor(s);
  const tenth = Math.floor((s - whole) * 10);
  return `${String(m).padStart(2, '0')}:${String(whole).padStart(2, '0')}.${tenth}`;
}

function barBeat(time: number, rhythm: DemoRhythm): string {
  let lo = 0, hi = rhythm.beats.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (rhythm.beats[mid].time <= time) lo = mid + 1; else hi = mid;
  }
  const beat = rhythm.beats[Math.max(0, lo - 1)];
  return beat ? `${String(beat.bar).padStart(2, '0')}·${beat.beat}` : '—·—';
}

export function Transport() {
  const { state, dispatch } = useStore();
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);

  const duration = state.doc.scenes[state.doc.scenes.length - 1]?.end_time ?? 242;
  const progress = Math.max(0, Math.min(1, state.transport.time / duration));
  const scene = state.doc.scenes.find(
    (s) => state.transport.time >= s.start_time && state.transport.time < s.end_time,
  );

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    dispatch({ type: 'transport-time', time: frac * duration });
  };

  return (
    <div className="transport">
      <div className="tp-in">
        <button
          className="tp-play"
          aria-label={state.transport.playing ? t('transport.pause') : t('transport.play')}
          onClick={() => dispatch({ type: 'transport-play', playing: !state.transport.playing })}
        >
          {state.transport.playing ? (
            <svg width="12" height="12" viewBox="0 0 12 12">
              <path d="M2.8 2h2.4v8H2.8zM6.8 2h2.4v8H6.8z" fill="#fbfaf7" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12">
              <path d="M3.5 2.2v7.6L9.8 6z" fill="#fbfaf7" />
            </svg>
          )}
        </button>
        <div className="tp-tl" onClick={seek} role="slider" aria-label="timeline" aria-valuenow={Math.round(progress * 100)}>
          <div className="tp-fill" style={{ width: `${progress * 100}%` }} />
          <div className="tp-knob" style={{ left: `${progress * 100}%` }} />
        </div>
        <span className="tp-time">{timeLabel(state.transport.time)}</span>
        <div className="tp-div" />
        <span className="tp-n">{barBeat(state.transport.time, state.rhythm)}</span>
        <span className="tp-sc">{scene?.title ?? '—'}</span>
        <div className="tp-div" />
        <button
          className={`tp-ic${state.transport.loopStart !== null ? ' on' : ''}`}
          title={t('transport.loop')}
          onClick={() => {
            const scene2 = scene;
            if (state.transport.loopStart !== null) {
              dispatch({ type: 'transport-loop', start: null, end: null });
            } else if (scene2) {
              dispatch({ type: 'transport-loop', start: scene2.start_time, end: scene2.end_time });
            }
          }}
        >
          <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M2 7.5a5.5 5.5 0 1 1 1.6 3.9M2 7.5V4.6M2 7.5h2.9" />
          </svg>
        </button>
        <span className="tp-n">{Math.round(state.camera.zoom * 100)}%</span>
      </div>
    </div>
  );
}
