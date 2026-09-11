/**
 * `Reset demo` — the LOCAL reset, and the one Demo Mode is allowed to use.
 *
 * It restores archived playback presentation state and nothing else:
 *
 *   - every lot becomes replayable from its first beat;
 *   - Incoming and Today return to the canonical opening projection;
 *   - retained read-model responses are dropped so the boards re-read.
 *
 * WHAT IT CANNOT DO, STRUCTURALLY
 *
 * It issues no request. There is no fetch in this file and no import of the
 * adapter, so there is no code path — not a bug, not a mistaken branch — by
 * which pressing `Reset demo` reaches `POST /reset-demo`, re-seeds the
 * authoritative corpus, touches a live DecisionRecord or starts a live run.
 *
 * That separation is enforced rather than asserted: the live reset lives behind
 * `resetDemo()` in the adapter, this one is a pure local clear, and
 * `ResetDemo.tsx` chooses between them on the current mode. A test asserts that
 * a demo-mode reset performs zero network calls, and another asserts the live
 * one still calls the authoritative endpoint.
 */

import { clearDecided } from './decided';
import { invalidateSurfaces } from '../features/useSurfaceData';

export function resetDemoPlayback(): void {
  clearDecided();
  // The boards cache their last authoritative response. After a reset that
  // response describes decisions that are no longer part of this session, so it
  // is dropped and the surfaces re-read the opening projection.
  invalidateSurfaces(['today', 'decisions']);
}
