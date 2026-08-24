import type {
  Command,
  DecisionRow,
  FixtureAdapter,
  FixtureId,
  ProductionLine,
  Screen,
  VouchViewModel,
} from './types';
import { DECISIONS, HALDEN_GROUPED } from '../dev/fixtures/decisions';
import { L2_SEQUENCE, LINES, RECOVERY } from '../dev/fixtures/production';
import { BASIS_CHAIN, RECORD_STEPS, RESUME_STEPS } from '../dev/fixtures/record';
import { RECORD_FILTERS, RECORD_ROWS, SUPPLIERS } from '../dev/fixtures/ledger';

/** All product state lives here. Commands are the only way it changes. */
export interface VouchState {
  screen: Screen;
  incident: boolean;
  disrupted: boolean;
  openLotId: string | null;
  resolvedLotIds: string[];
}

export const INITIAL_STATE: VouchState = {
  screen: 'incoming',
  incident: false,
  disrupted: false,
  openLotId: null,
  resolvedLotIds: [],
};

const byId = new Map<string, DecisionRow>([...DECISIONS, HALDEN_GROUPED].map((d) => [d.lotId, d]));

/** Deterministic reducer. No timers, no fetch — state moves only on a command. */
export function reduce(state: VouchState, cmd: Command): VouchState {
  switch (cmd.type) {
    case 'NAVIGATE':
      return { ...state, screen: cmd.screen, openLotId: null };
    case 'OPEN_LOT':
      // A ledger row that has no decision detail navigates to its record instead.
      return byId.has(cmd.lotId)
        ? { ...state, openLotId: cmd.lotId }
        : { ...state, screen: 'record', openLotId: null };
    case 'PROVIDE_EVIDENCE':
      // The same record resolves in place. No new case is created.
      return state.resolvedLotIds.includes(cmd.lotId)
        ? state
        : { ...state, resolvedLotIds: [...state.resolvedLotIds, cmd.lotId] };
    case 'CLOSE_DRAWER':
      return { ...state, openLotId: null };
  }
}

function lineNote(line: { name: string }, disrupted: boolean) {
  return line.name.startsWith('Line 2') && disrupted ? 'plan changed 09:41' : 'all covered';
}

function buildLines(disrupted: boolean): ProductionLine[] {
  return LINES.map((ln) => {
    const isL2 = ln.name.startsWith('Line 2');
    const expanded = disrupted && isL2;
    return {
      name: ln.name,
      orders: ln.orders,
      note: lineNote(ln, disrupted),
      expanded,
      // Unrelated lines get quieter, they never vanish.
      deEmphasized: disrupted && !isL2,
    };
  });
}

export function selectView(state: VouchState): VouchViewModel {
  const needsYou = state.incident ? [HALDEN_GROUPED, ...DECISIONS] : DECISIONS;
  const openRow = state.openLotId ? byId.get(state.openLotId) : undefined;

  // The count is lots needing a decision, not rows. The Halden incident is one
  // row standing for 18 lots, so 18 grouped + 6 individual = 24.
  const needDecision = needsYou.reduce((n, r) => n + (r.groupedCount ?? 1), 0);

  return {
    screen: state.screen,
    navBadge: needDecision,
    incoming: {
      // 6 + 17 + 164 = 187 · 151 + 13 = 164
      rail: { arrived: 187, needDecision, inProgress: 17, completed: 164 },
      incident: state.incident
        ? {
            headline: 'SUPPLIER INCIDENT',
            body: ' reported a manufacturing deviation at 08:20. 18 in-transit lots were re-held pending one governing decision.',
          }
        : undefined,
      needsYou,
      inProgress: [
        { n: '5', label: 'parsing COA' },
        { n: '7', label: 'assembling evidence' },
        { n: '4', label: 'verifying' },
        { n: '1', label: 'awaiting lab upload' },
      ],
      completed: { released: 151, quarantined: 13, reopened: 0 },
    },
    today: {
      // 40 + 3 + 0 = 43 normal · 39 + 3 + 1 = 43 disrupted
      readiness: state.disrupted
        ? [
            { count: 39, readiness: 'READY', sub: 'incl. resequenced C-418' },
            { count: 3, readiness: 'AT_RISK', sub: 'C-419 · Quality decision pending' },
            { count: 1, readiness: 'BLOCKED', sub: 'C-417 · uncovered' },
          ]
        : [
            { count: 40, readiness: 'READY', sub: 'coverage confirmed' },
            { count: 3, readiness: 'AT_RISK', sub: 'unresolved evidence' },
            { count: 0, readiness: 'BLOCKED', sub: 'lines calm' },
          ],
      lines: buildLines(state.disrupted),
      disruption: state.disrupted
        ? {
            lotId: 'L-2231',
            material: 'Resin R-17',
            coaClaim: 'COA CONFORMS',
            disposition: '⊘ QUARANTINED',
            consequence: '— fails Spec S-88 Rev 4. Coverage of C-417 removed.',
            sequence: L2_SEQUENCE,
            recovery: RECOVERY,
            resequence: {
              badge: 'RESEQUENCED',
              line: 'C-418 pulled into the 09:30 slot — materials released, Line 2 feasible.',
              result: '09:30 SLOT RECOVERED',
              caveat: 'C-417 remains blocked',
            },
          }
        : undefined,
    },
    record: {
      lotId: 'L-2231',
      material: 'Resin R-17',
      meta: 'Dispositioned 09:41 · shipment 88-4471 · Meridian Polymers',
      disposition: '⊘ QUARANTINED',
      dispositionNote: 'Independently verified · reversible on new evidence',
      basisChain: BASIS_CHAIN,
      steps: RECORD_STEPS,
    },
    drawer: openRow
      ? {
          row: openRow,
          resolved: state.resolvedLotIds.includes(openRow.lotId),
          resumeSteps: RESUME_STEPS,
        }
      : undefined,
    suppliers: { rows: SUPPLIERS, shown: '5 of 214' },
    records: { rows: RECORD_ROWS, total: '3,481', filters: RECORD_FILTERS },
  };
}

const FIXTURE_STATES: Record<FixtureId, VouchState> = {
  'incoming-normal': { ...INITIAL_STATE },
  'incoming-incident': { ...INITIAL_STATE, incident: true },
  'today-normal': { ...INITIAL_STATE, screen: 'today' },
  'today-disrupted': { ...INITIAL_STATE, screen: 'today', disrupted: true },
  'decision-record': { ...INITIAL_STATE, screen: 'record' },
  'quality-decision': { ...INITIAL_STATE, openLotId: 'L-2262' },
  resolved: { ...INITIAL_STATE, openLotId: 'L-2262', resolvedLotIds: ['L-2262'] },
  suppliers: { ...INITIAL_STATE, screen: 'suppliers' },
  records: { ...INITIAL_STATE, screen: 'records' },
};

export function fixtureState(id: FixtureId): VouchState {
  return { ...FIXTURE_STATES[id] };
}

export const fixtureAdapter: FixtureAdapter = {
  getView: (id) => selectView(fixtureState(id)),
};
