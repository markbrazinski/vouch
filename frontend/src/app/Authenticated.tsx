/**
 * The authentication gate.
 *
 * Renders the product only once the backend has confirmed a session. While the
 * check is in flight it renders nothing — deliberately, because flashing the
 * shell and then replacing it with a sign-in form would show a judge a moment
 * of an application they are not yet signed in to.
 *
 * This gate is a UX affordance, NOT the security boundary. Every `/api` route
 * is refused server-side without a valid session cookie (`bff/handler.py`), so
 * removing this component would change what a browser DISPLAYS and nothing at
 * all about what it can read or start. Putting the real check anywhere a
 * browser can reach would be putting it where a browser can remove it.
 */

import { useCallback, useEffect, useState } from 'react';
import { session } from '../adapter/client';
import { SignIn } from './SignIn';

export function Authenticated({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'checking' | 'in' | 'out'>('checking');

  const check = useCallback(() => {
    let cancelled = false;
    void session().then(({ authenticated }) => {
      if (!cancelled) setState(authenticated ? 'in' : 'out');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(check, [check]);

  if (state === 'checking') return null;
  if (state === 'out') return <SignIn onSignedIn={() => setState('in')} />;
  return <>{children}</>;
}
