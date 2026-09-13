import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/shell.css';
import './styles/paper.css';
import MovieStudio from './movie/Studio';

/* One screen: the movie studio. Direction and composition remain headless
   contracts for Agent-authored work; they are deliberately not another UI. */
const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <MovieStudio />
    </StrictMode>,
  );
}
