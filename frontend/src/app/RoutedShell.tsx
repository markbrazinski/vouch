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

import { useEffect } from 'react';
import {
  NavLink,
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
import { useFilmReset } from '../dev/useFilmReset';
import {
  prefetchSurfaces,
  RecordSurface,
  RecordsIndexSurface,
  SuppliersSurface,
  TodaySurface,
} from '../features/Surfaces';

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

  /**
   * Shift+R resets the LOT-1006 scenario while filming. DEV-only: the hook
   * registers no listener in a production build.
   *
   * After a reset the shell routes to Incoming, which re-reads authoritative
   * state — the lot is RECEIVED again and C-419 is back to AT_RISK, so the
   * next take starts from the canonical picture rather than a cached one.
   */
  const { toast } = useFilmReset(() => {
    prefetchSurfaces([
      { key: 'today', load: getToday },
      { key: 'decisions', load: () => listDecisions(50) },
    ]);
    navigate('/incoming');
  });

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
      {toast && (
        <div
          data-testid="film-reset-toast"
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
          {toast}
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
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                /* A nav click is a navigation, not a request to reset someone
                   else's state. `/incoming` means "show current arrivals"
                   whatever the operator was looking at — including a decision
                   that was opened from Incoming, which is the case the old
                   state-based shell could not express. */
                style={({ isActive }) => ({
                  textAlign: 'left',
                  background: isActive ? 'rgba(255,255,255,.08)' : 'transparent',
                  border: 'none',
                  borderRadius: 9,
                  padding: '9px 12px',
                  cursor: 'pointer',
                  font: `600 12.5px ${SANS}`,
                  color: isActive ? '#FAFAFA' : '#B3AC9E',
                  textDecoration: 'none',
                })}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
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
