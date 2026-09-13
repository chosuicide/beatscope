/**
 * Toasts (≤ 3 visible, 400 ms motion) and the WebGL-unavailable fallback.
 */
import { useEffect } from 'react';
import { useStore } from '../app/store';
import { translate } from '../app/i18n';

export function Toasts() {
  const { state, dispatch } = useStore();
  useEffect(() => {
    if (state.toasts.length === 0) return;
    const timers = state.toasts.map((toast) =>
      window.setTimeout(() => dispatch({ type: 'toast-expire', id: toast.id }), 2600),
    );
    return () => timers.forEach(clearTimeout);
  }, [state.toasts, dispatch]);

  return (
    <div className="toasts" aria-live="polite">
      {state.toasts.slice(0, 3).map((toast) => (
        <div className="toast" key={toast.id}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}

export function NoGl() {
  const { state } = useStore();
  if (state.webglAvailable) return null;
  return (
    <div className="nogl">
      <div className="nogl-card">
        <h2>{translate(state.language, 'canvas.webglUnavailable.title')}</h2>
        <p>{translate(state.language, 'canvas.webglUnavailable.body')}</p>
      </div>
    </div>
  );
}
