/**
 * Prompt / package inspector (frozen frame D): the direction proposal review
 * UI plus the export-package checklist.
 */
import { useState } from 'react';
import { useStore } from '../app/store';
import { translate } from '../app/i18n';

export function PackagePanel() {
  const { state, dispatch } = useStore();
  const t = (key: string, params?: Record<string, string | number>) =>
    translate(state.language, key, params);
  const [rawOpen, setRawOpen] = useState(false);
  const proposal = state.proposal;
  if (!state.panels.packageOpen || !proposal) return null;

  const added = proposal.changes.filter((c) => c.sign === '+');
  const changed = proposal.changes.filter((c) => c.sign === '±');
  const removed = proposal.changes.filter((c) => c.sign === '−');

  const closePanel = () => dispatch({ type: 'panels', packageOpen: false, inspectorOpen: true });

  return (
    <aside className="insp wide">
      <div className="icrumb">
        {t('proposal.crumb', { project: state.doc.project_title, index: String(proposal.index).padStart(2, '0') })}
      </div>
      <div className="ihead">
        <h2>{t('proposal.title')}</h2>
        <span className="kchip">{t(`proposal.state.${state.proposalState}`)}</span>
        <button className="ibtn" onClick={closePanel} aria-label="close">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 3.5 5.5 8 10 12.5" />
          </svg>
        </button>
      </div>
      <p className="note" style={{ padding: '8px 16px 0', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
        {t('proposal.source')}
      </p>

      <div className="isec">
        <h3>{t('proposal.section.summary')}</h3>
        <div className="irow">
          <span className="ilab">{t('proposal.label.intent')}</span>
          <span style={{ fontSize: 13, letterSpacing: '-.008em', lineHeight: '18px' }}>{proposal.intent}</span>
        </div>
        <div className="irow">
          <span className="ilab">{t('proposal.label.scope')}</span>
          <span className="dmono" style={{ color: 'var(--ink-0)' }}>{proposal.scope}</span>
        </div>
        <div className="irow">
          <span className="ilab">{t('proposal.label.basis')}</span>
          <span className="dmono" style={{ color: 'var(--ink-0)' }}>{proposal.basis}</span>
        </div>
      </div>

      <div className="isec">
        <h3>{t('proposal.section.changes')}</h3>
        <div className="dsum">
          <span>{`+${added.length} ${t('proposal.group.added').toLowerCase()}`}</span>
          <span>{`±${changed.length} ${t('proposal.group.changed').toLowerCase()}`}</span>
          <span>{`−${removed.length} ${t('proposal.group.removed').toLowerCase()}`}</span>
        </div>
        <div className="dg">
          <h4>{t('proposal.group.added')}</h4>
          {added.map((c, i) => (
            <div className="drow2" key={`a${i}`}>
              <span className="sg">+</span>
              <span>
                {c.scene} / {c.system}
                <span className="sub">{c.detail}</span>
              </span>
            </div>
          ))}
          <h4>{t('proposal.group.changed')}</h4>
          {changed.map((c, i) => (
            <div className="drow2" key={`c${i}`}>
              <span className="sg">±</span>
              <span>
                {c.scene} / {c.system}
                <span className="sub">
                  {c.detail} <span className="dmono">{`${c.before} → ${c.after}`}</span>
                </span>
              </span>
            </div>
          ))}
          <h4>{t('proposal.group.removed')}</h4>
          {removed.length === 0 ? (
            <div className="drow2" style={{ color: 'var(--ink-2)' }}>
              <span className="sg">−</span>
              <span>{t('proposal.group.none')}</span>
            </div>
          ) : (
            removed.map((c, i) => (
              <div className="drow2" key={`r${i}`}>
                <span className="sg">−</span>
                <span>
                  {c.scene} / {c.system}
                  <span className="sub">{c.detail}</span>
                </span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="isec">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            className="btn-ink"
            style={{ height: 30, lineHeight: '30px' }}
            onClick={() => {
              dispatch({ type: 'proposal', proposal, state: 'applied' });
              dispatch({ type: 'toast', text: 'Direction patch applied' });
            }}
          >
            {t('proposal.action.apply')}
          </button>
          <button
            className="tbtn"
            onClick={() => {
              dispatch({ type: 'proposal', proposal, state: 'rejected' });
              dispatch({ type: 'toast', text: 'Proposal rejected' });
            }}
          >
            {t('proposal.action.reject')}
          </button>
        </div>
        <div
          className="resrow"
          style={{ marginTop: 8 }}
          onClick={() => setRawOpen((v) => !v)}
        >
          <svg className="chev" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            {rawOpen ? <path d="M10 3.5 5.5 8 10 12.5" /> : <path d="M6 3.5 10.5 8 6 12.5" />}
          </svg>
          <span className="rt" style={{ color: 'var(--ink-1)' }}>{t('proposal.rawJson')}</span>
          <span className="note">{t('proposal.rawJson.lines', { n: proposal.rawLines.length })}</span>
        </div>
        {rawOpen && (
          <pre className="dmono" style={{ margin: '6px 0 0', whiteSpace: 'pre-wrap', color: 'var(--ink-1)' }}>
            {proposal.rawLines.join('\n')}
          </pre>
        )}
      </div>

      <div className="isec">
        <h3>{t('export.section.title')}</h3>
        <div className="ckrow">
          <span className="ic">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="8" r="6.5" />
              <path d="M5.2 8.2 7.2 10.2 10.8 6.2" />
            </svg>
          </span>
          {t('export.check.references')}
          <span className="val">{t('export.check.verified', { n: 12 })}</span>
        </div>
        <div className="ckrow">
          <span className="ic">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="8" r="6.5" />
              <path d="M5.2 8.2 7.2 10.2 10.8 6.2" />
            </svg>
          </span>
          {t('export.check.assets')}
          <span className="val">{t('export.check.assetsValue', { count: 3, size: '4.6 MB' })}</span>
        </div>
        <div className="ckrow mut">
          <span className="ic">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="8" cy="8" r="6.5" />
              <path d="M5.5 8h5" />
            </svg>
          </span>
          {t('export.check.audio')}
          <span className="val">{t('export.check.audioExcluded')}</span>
        </div>
        <div className="trow2">
          <button
            className="btn-line"
            onClick={() => {
              window.dispatchEvent(new CustomEvent('beathi:export-package'));
              if (state.coach.visible) dispatch({ type: 'coach', visible: false });
            }}
          >
            {t('export.action.export')}
          </button>
          <button
            className="tbtn"
            onClick={() => {
              void navigator.clipboard?.writeText(proposal.rawLines.join('\n')).catch(() => {});
              dispatch({ type: 'toast', text: t('export.copied') });
            }}
          >
            {t('export.action.copyChecklist')}
          </button>
        </div>
      </div>
    </aside>
  );
}
