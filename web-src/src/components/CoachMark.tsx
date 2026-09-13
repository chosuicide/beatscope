/**
 * First-run coach mark (frozen frame A, compact sm variant at 238 px).
 * Coordinates are stage-relative in the frozen frame (810, 470); the stage
 * origin moves with the dock, so the offset is recomputed here.
 * Steps advance on the product main path: select → change response → export.
 */
import { useStore } from '../app/store';
import { translate } from '../app/i18n';

const STAGE_LEFT_OPEN = 280;
const STAGE_LEFT_CLOSED = 52;
const STAGE_TOP = 48;
const COACH_LEFT = 810;
const COACH_TOP = 470;

export function CoachMark() {
  const { state, dispatch } = useStore();
  if (!state.coach.visible || state.selection.sceneId) return null;
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);
  const step = state.coach.step;
  const left = (state.panels.dockOpen ? STAGE_LEFT_OPEN : STAGE_LEFT_CLOSED) + COACH_LEFT;
  const top = STAGE_TOP + COACH_TOP;

  return (
    <div className="coach sm" style={{ left, top }}>
      <h2>{t('canvas.coach.title')}</h2>
      <div className="sub">{t('canvas.coach.subtitle', { project: state.doc.project_title })}</div>
      {([1, 2, 3] as const).map((n) => (
        <div className={`cstep${n <= step ? ' done' : ''}`} key={n}>
          <span className="n">{n}</span>
          <p>{t(`canvas.coach.step${n}`)}</p>
        </div>
      ))}
      <div className="cfoot">
        <div className="dots">
          <i className={step === 1 ? 'on' : ''} />
          <i className={step === 2 ? 'on' : ''} />
          <i className={step === 3 ? 'on' : ''} />
        </div>
        <button className="tbtn" style={{ padding: '2px 6px', fontSize: 12 }} onClick={() => dispatch({ type: 'coach', visible: false })}>
          {t('canvas.coach.skip')}
        </button>
      </div>
    </div>
  );
}
