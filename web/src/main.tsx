import { render } from 'preact';
import '@fontsource-variable/fraunces/opsz.css';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import './styles/tokens.css';
import './styles/components.css';
import './styles/app.css';
import { App } from './app';
import { watchKeyboard } from './lib/keyboard';

// The app restores the overview's scroll position itself when coming back from a recipe.
if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual';

watchKeyboard();

render(<App />, document.getElementById('app')!);

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // The app works without it; only offline reading is missing.
    });
  });
}
