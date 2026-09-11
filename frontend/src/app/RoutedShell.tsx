/**
 * The application shell, and the one place navigation is decided.
 *
 * Location used to be component state: a `surface` in the shell, an
 * `openRecordId` beside it, and an `openLot` two levels down inside the
 * Incoming page. Those disagreed, because nothing kept them in step. Opening a
 * lot set `openLot`, clicking Incoming set `surface` to a value it already
 * held, React saw no reason to remount, and the operator was left inside a
 * decision with no way back to the list.
 *
 * The fix is not another reset callback or a forced remount — both leave
 * location scattered across the tree. The URL is now the single answer to
 * "where am I", and every surface is reached by routing to it. Back and Forward
 * work because the history stack is the real one, and a refresh reconstructs
 * the surface from authoritative backend state.
 *
 * What did NOT move into the route: whether the source-document modal is open,
 * which stage is expanded, and every other purely visual disclosure. Those
 * answer "what is happening in the product", not "where am I".
 */

import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom';
import { DecisionRoute } from '../decision/DecisionRoute';
import { IncomingRoute } from '../decision/IncomingRoute';
import type { ArrivalDocuments, HeroAEntry } from '../decision/entry';
import { INK, MONO, N, SANS, HAIR } from '../decision/primitives';
import { getToday, listDecisions } from '../adapter/client';
import { ResetDemo } from './ResetDemo';
import { DemoBadge, DemoToggle } from './DemoToggle';
import { DEMO_AVAILABLE } from '../demo/mode';
import {
  prefetchSurfaces,
  RecordSurface,
  RecordsIndexSurface,
  SuppliersSurface,
  TodaySurface,
} from '../features/Surfaces';

/**
 * The archived-run view, loaded only when this build enables Demo Mode.
 *
 * `lazy` puts it in its own chunk and `DEMO_AVAILABLE` is a build-time
 * constant, so a judge build never emits that chunk and never registers the
 * route. The judge bundle does not contain a disabled demo mode; it does not
 * contain demo mode. See `demo/mode.ts`.
 */
const DemoRoute = DEMO_AVAILABLE
  ? lazy(() => import('../demo/DemoRoute').then((m) => ({ default: m.DemoRoute })))
  : null;

const NAV = [
  { to: '/today', label: 'Today' },
  { to: '/incoming', label: 'Incoming' },
  { to: '/suppliers', label: 'Suppliers' },
  { to: '/records', label: 'Records' },
];

/**
 * The header title, derived from the route rather than tracked alongside it.
 *
 * A second piece of state saying which surface is showing is exactly the class
 * of bug this change removes, so the path is read directly.
 */
function titleFor(pathname: string): [string, string] {
  if (pathname.startsWith('/today')) return ['Today', 'Production readiness'];
  if (pathname.startsWith('/incoming')) return ['Incoming', 'Quality · arrivals awaiting decision'];
  if (pathname.startsWith('/decisions')) return ['Decision', 'Live authority workspace'];
  if (DEMO_AVAILABLE && pathname.startsWith('/demo/'))
    return ['Decision', 'Authority workspace'];
  if (pathname.startsWith('/suppliers')) return ['Suppliers', 'Approved material sources'];
  if (pathname.startsWith('/records')) return ['Records', 'Every disposition, searchable'];
  return ['Vouch', ''];
}

/** A route back to a list. Real navigation, never a state reset. */
export function BackBar({ label, to }: { label: string; to: string }) {
  const navigate = useNavigate();
  return (
    <div style={{ padding: '14px 30px 0' }}>
      <button
        type="button"
        onClick={() => navigate(to)}
        style={{
          background: 'transparent',
          border: `1px solid ${HAIR}`,
          borderRadius: 7,
          padding: '5px 11px',
          font: `600 11.5px ${SANS}`,
          color: INK.prose,
          cursor: 'pointer',
        }}
      >
        &larr; {label}
      </button>
    </div>
  );
}

/**
 * One durable DecisionRecord, as an audit projection.
 *
 * Distinct from `/decisions/:recordId` as a user job: this is the record of a
 * decision that was made, reached from the ledger. It renders the same
 * workspace because that IS the audit view of a decision — but it never starts
 * or polls anything.
 */
function RecordDetailRoute() {
  const { recordId } = useParams();
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <BackBar label="Back to Records" to="/records" />
      <RecordSurface decisionRecordId={recordId!} />
    </div>
  );
}

/** A scrolling frame for the list surfaces. The workspace scrolls its own. */
function Scroller({ children }: { children: React.ReactNode }) {
  return <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>{children}</div>;
}

export function RoutedShell({
  entry,
  arrivals = {},
}: {
  entry: HeroAEntry;
  /** Every canonical arrival and its certificate, keyed by lot. */
  arrivals?: ArrivalDocuments;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [title, sub] = titleFor(location.pathname);

  /**
   * Warm Today and the decision list together, once, at startup.
   *
   * Each authoritative read costs a measured 3.4-4.5s of fixed runtime
   * overhead, and surfaces mount on demand — so without this the first visit to
   * each surface pays that serially. Prefetching in parallel overlaps them, and
   * `useSurfaceData` retains the real response so a revisit renders at once and
   * revalidates behind. No fixture is involved at any point.
   */
  useEffect(() => {
    prefetchSurfaces([
      { key: 'today', load: getToday },
      { key: 'decisions', load: () => listDecisions(50) },
    ]);
  }, []);

  /** Confirmation that a reset landed. Whose reset it was is ResetDemo's call. */
  const [resetToast, setResetToast] = useState<string | null>(null);

  /**
   * Re-read everything after a reset, then land on Today.
   *
   * The authoritative read models must be refetched, not just re-rendered: the
   * server state changed underneath a UI that had already cached it, and
   * showing the old board after a reset is exactly the bug this avoids.
   */
  const afterReset = useCallback(
    (message: string) => {
      prefetchSurfaces([
        { key: 'today', load: getToday },
        { key: 'decisions', load: () => listDecisions(50) },
      ]);
      navigate('/today');
      setResetToast(message);
    },
    [navigate],
  );

  useEffect(() => {
    if (!resetToast) return;
    const timer = window.setTimeout(() => setResetToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [resetToast]);

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 14,
        padding: '20px 0 40px',
        background: '#CFC9BD',
      }}
    >
      {resetToast && (
        <div
          data-testid="reset-toast"
          role="status"
          style={{
            position: 'fixed',
            bottom: 20,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 100,
            background: INK.primary,
            color: '#F6F3EC',
            font: `600 12px ${MONO}`,
            padding: '9px 16px',
            borderRadius: 8,
            boxShadow: '0 8px 24px rgba(0,0,0,.3)',
          }}
        >
          {resetToast}
        </div>
      )}

      <div
        data-testid="acceptance-frame"
        style={{
          width: 1600,
          height: 900,
          maxWidth: '100%',
          display: 'flex',
          position: 'relative',
          background: N.frame,
          overflow: 'hidden',
          boxShadow: '0 1px 0 rgba(0,0,0,.04)',
        }}
      >
        <aside
          style={{
            width: 224,
            flex: 'none',
            background: INK.primary,
            color: N.chip,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{ padding: '24px 22px 20px', borderBottom: '1px solid rgba(255,255,255,.09)' }}
          >
            <div
              style={{
                fontFamily: "'Jost', sans-serif",
                fontWeight: 700,
                fontSize: 27,
                letterSpacing: '-.02em',
                color: '#FAFAFA',
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
              }}
            >
              ÅBY&nbsp;PLANT
            </div>
          </div>

          <nav style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            {NAV.map((item) => {
              const isActive = location.pathname.startsWith(item.to);
              return (
                /* A BUTTON, not an anchor.
                 *
                 * An `<a href>` makes the browser paint its own status bubble —
                 * "localhost:5173/today" — in the bottom-left corner on hover.
                 * Nothing on the page can suppress it (that is deliberate,
                 * anti-phishing), and it lands in every frame of a screen
                 * recording where the cursor crosses the nav.
                 *
                 * Navigation itself is unchanged: `navigate()` pushes the same
                 * history entry the link did, so Back, Forward and a refresh on
                 * any routed path all behave exactly as before. What is lost is
                 * middle-click-to-new-tab, which this app has no use for — it is
                 * a single-window operator console.
                 *
                 * A nav click is a navigation, not a request to reset someone
                 * else's state. `/incoming` means "show current arrivals"
                 * whatever the operator was looking at — including a decision
                 * that was opened from Incoming, which is the case the old
                 * state-based shell could not express. */
                <button
                  key={item.to}
                  type="button"
                  onClick={() => navigate(item.to)}
                  aria-current={isActive ? 'page' : undefined}
                  style={{
                    textAlign: 'left',
                    background: isActive ? 'rgba(255,255,255,.08)' : 'transparent',
                    border: 'none',
                    borderRadius: 9,
                    padding: '9px 12px',
                    cursor: 'pointer',
                    font: `600 12.5px ${SANS}`,
                    color: isActive ? '#FAFAFA' : '#B3AC9E',
                    textDecoration: 'none',
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>

          {/* Bottom of the left nav. The toggle chooses the execution mode;
              the reset below it IS that mode's reset — server-side and
              authoritative in live mode, local and request-free in demo mode.
              See ResetDemo for why the two cannot reach each other. */}
          <DemoToggle />
          <ResetDemo onReset={afterReset} />
        </aside>

        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            background: N.frame,
          }}
        >
          <header
            style={{
              height: 58,
              flex: 'none',
              borderBottom: `1px solid ${HAIR}`,
              background: N.card,
              display: 'flex',
              alignItems: 'center',
              padding: '0 26px',
              gap: 16,
            }}
          >
            <h1
              style={{
                margin: 0,
                font: `700 15px ${SANS}`,
                color: INK.primary,
                letterSpacing: '-.01em',
              }}
            >
              {title}
            </h1>
            <div style={{ font: `400 12px ${MONO}`, color: INK.label }}>{sub}</div>
            {/* Never "LIVE" during archived playback. What is on screen really
                happened, but it is not happening now, and the header says so. */}
            <div style={{ marginLeft: 'auto' }}>
              <DemoBadge />
            </div>
          </header>

          <Routes>
            <Route path="/" element={<Navigate to="/today" replace />} />
            <Route
              path="/today"
              element={
                <Scroller>
                  {/* Today's causal history carries the real decision record
                      that produced each change, so "Why did this change?" opens
                      that document. An order card with no causal link still
                      falls back to the ledger rather than guessing. */}
                  <TodaySurface
                    onOpenDecision={(id) =>
                      navigate(id.startsWith('DR-') ? `/records/${id}` : '/records')
                    }
                  />
                </Scroller>
              }
            />
            <Route path="/incoming" element={<IncomingRoute arrivals={arrivals} />} />
            <Route path="/decisions/:recordId" element={<DecisionRoute entry={entry} />} />
            {/* One archived run, replayed in the real workspace. Reached by
                clicking a lot while Demo Mode is on — the same click that
                starts a live evaluation when it is off. */}
            {DemoRoute && (
              <Route
                path="/demo/:lotId"
                element={
                  <Suspense fallback={null}>
                    <DemoRoute />
                  </Suspense>
                }
              />
            )}
            <Route
              path="/suppliers"
              element={
                <Scroller>
                  <SuppliersSurface onOpen={(id) => navigate(`/records/${id}`)} />
                </Scroller>
              }
            />
            <Route
              path="/records"
              element={
                <Scroller>
                  <RecordsIndexSurface onOpen={(id) => navigate(`/records/${id}`)} />
                </Scroller>
              }
            />
            <Route path="/records/:recordId" element={<RecordDetailRoute />} />
            {/* An unknown path is not a reason to show someone else's
                decision. Today is the product's home, and the redirect is
                explicit rather than a silent fallback into a surface that
                would look like an answer. */}
            <Route path="*" element={<Navigate to="/today" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
