import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/tokens.css';
import './styles/shell.css';
import './styles/paper.css';
import MovieStudio from './movie/Studio';

/* One screen: the movie studio. The canvas workspace and the composition
   workspace were removed with their views; the runtime, motion, direction and
   document-model modules they were built on stay, because the renderer, the
   agent export and the test suite still use them. */
const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <MovieStudio />
    </StrictMode>,
  );
}
