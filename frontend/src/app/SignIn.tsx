/**
 * The judge sign-in screen.
 *
 * A username and a password, and nothing else. No sign-up link, no password
 * reset, no email verification, no "remember me" — the pool is admin-create-only
 * with recovery disabled, so offering any of those would be offering a door
 * that is not there.
 *
 * The credential never persists in the browser. It is POSTed once; the BFF
 * checks it against Cognito server-side and replies with an HttpOnly cookie
 * this code cannot read. There is deliberately no token in component state,
 * no localStorage write, and nothing to put in a URL.
 */

import { useState, type FormEvent } from 'react';
import { login } from '../adapter/client';
import { INK, MONO, SANS, HAIR } from '../decision/primitives';

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      if (await login(username, password)) {
        onSignedIn();
        return;
      }
      setFailed(true);
      // Clear the password, never the username. A wrong password is worth
      // retyping; making someone retype a correct username is just friction.
      setPassword('');
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const field = {
    width: '100%',
    boxSizing: 'border-box' as const,
    padding: '9px 11px',
    borderRadius: 7,
    border: `1px solid ${HAIR}`,
    background: '#FFFDF9',
    font: `500 13px ${SANS}`,
    color: INK.primary,
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#CFC9BD',
        padding: 20,
      }}
    >
      <form
        onSubmit={submit}
        style={{
          width: 340,
          background: '#F6F3EC',
          borderRadius: 12,
          padding: '30px 28px',
          boxShadow: '0 10px 40px rgba(0,0,0,.16)',
        }}
      >
        <div
          style={{
            fontFamily: "'Jost', sans-serif",
            fontWeight: 700,
            fontSize: 30,
            letterSpacing: '-.02em',
            color: INK.primary,
            lineHeight: 1,
          }}
        >
          Vouch
        </div>
        <div
          style={{
            font: `500 10px/1 ${MONO}`,
            letterSpacing: '.12em',
            color: '#8F887A',
            marginTop: 8,
            marginBottom: 24,
          }}
        >
          ÅBY&nbsp;PLANT
        </div>

        <label style={{ display: 'block', marginBottom: 13 }}>
          <span style={{ font: `600 11px ${SANS}`, color: INK.prose, display: 'block', marginBottom: 5 }}>
            Username
          </span>
          <input
            name="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={field}
          />
        </label>

        <label style={{ display: 'block', marginBottom: 20 }}>
          <span style={{ font: `600 11px ${SANS}`, color: INK.prose, display: 'block', marginBottom: 5 }}>
            Password
          </span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={field}
          />
        </label>

        {failed && (
          <div
            role="alert"
            style={{
              font: `600 11.5px ${SANS}`,
              color: '#8C2F1D',
              marginBottom: 14,
            }}
          >
            Sign-in failed. Check the username and password.
          </div>
        )}

        <button
          type="submit"
          disabled={busy || !username || !password}
          style={{
            width: '100%',
            padding: '10px 0',
            borderRadius: 7,
            border: 'none',
            background: INK.primary,
            color: '#F6F3EC',
            font: `600 12.5px ${SANS}`,
            cursor: busy ? 'default' : 'pointer',
            opacity: busy || !username || !password ? 0.55 : 1,
          }}
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
