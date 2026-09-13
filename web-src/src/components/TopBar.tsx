/**
 * Top project bar (frozen frame A): mark, project name, save state,
 * language switch, and the Present / Preview / Export actions.
 */
import { useStore } from '../app/store';
import { translate } from '../app/i18n';

export function TopBar({ mode }: { mode: 'local-studio' | 'static-demo' }) {
  const { state, dispatch } = useStore();
  const t = (key: string) => translate(state.language, key);

  return (
    <header className="topbar">
      <svg className="mark" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="1" y="1" width="22" height="22" rx="6" fill="#171719" />
        <path
          d="M7 16.5V8.5M12 16.5v-6M17 16.5v-3.5"
          stroke="#fbfaf7"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
      </svg>
      <div className="tb-name">{state.doc.project_title}</div>
      <div className="tb-dot" />
      <div className="tb-save">{t(`topbar.saveState.${state.saveState}`)}</div>
      <div className="tb-sp" />
      {mode === 'static-demo' && (
        <button
          className="tbtn"
          onClick={() => {
            dispatch({ type: 'toast', text: translate(state.language, 'demo.persistNote') });
          }}
        >
          {t('demo.reset')}
        </button>
      )}
      <button className="tbtn lang" onClick={() => dispatch({ type: 'language', language: state.language === 'en' ? 'zh-CN' : 'en' })}>
        {state.language === 'en' ? '中文' : 'EN'}
      </button>
      <button className="tbtn">{t('topbar.action.present')}</button>
      <button className="btn-line">{t('topbar.action.preview')}</button>
      <button className="btn-ink">{t('topbar.action.export')}</button>
    </header>
  );
}
