import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './app/global.css';
import { VouchApp } from './app/VouchApp';

const root = createRoot(document.getElementById('root')!);

// The dev fixture harness is referenced only inside this `import.meta.env.DEV`
// branch. Vite replaces DEV with `false` in a production build, so the branch
// and its dynamic import are dropped and the harness chunk is never emitted.
if (import.meta.env.DEV && window.location.pathname === '/dev/vouch-states') {
  void import('./dev/VouchStateHarness').then(({ VouchStateHarness }) =>
    root.render(
      <StrictMode>
        <VouchStateHarness />
      </StrictMode>,
    ),
  );
} else {
  root.render(
    <StrictMode>
      <VouchApp />
    </StrictMode>,
  );
}
