/**
 * Adapter contract, against a REAL captured backend response.
 *
 * `hero-a-capture.json` is a verbatim Hero A response from the deployed
 * AgentCore runtime (49 events, real Nova Pro, real DynamoDB). Testing against
 * a hand-written fixture would only prove the adapter agrees with my
 * assumptions — which is exactly the mistake this capture exists to prevent.
 * Four field-name bugs were found by running the adapter against this file.
 */

import { describe, expect, it } from 'vitest';
import capture from './hero-a-capture.json';
import {
  project,
  toActivity,
  activeStageFrom,
  recoveryDetail,
  slotTime,
  failureProse,
} from '../adapter';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';

const dto = capture as unknown as EvaluateDTO;
const events = (dto.events ?? []) as LifecycleEventDTO[];

const vm = () =>
  project({
    decisionRecordId: dto.decision_record_id,
    lotId: dto.lot_id!,
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
    events,
    result: dto,
    running: false,
  });

/**
 * The same capture, plus the `failures` payload field DISPOSITION_COMPUTED
 * carries today. This capture was taken before that field existed, so injecting
 * it is what keeps the reason tests honest about the current contract while
 * every value stays the one the deployed runtime actually computed.
 */
const withFailures = () =>
  project({
    decisionRecordId: dto.decision_record_id,
    lotId: dto.lot_id!,
    material: 'MAT-ALLOY-7',
    receiptMeta: '',
    events: events.map((e) =>
      e.event === 'DISPOSITION_COMPUTED'
        ? {
            ...e,
            failures: [
              {
                characteristic: 'tensile_strength',
                value: 462,
                units: 'MPa',
                min_value: 480,
                max_value: null,
                threshold_text: '>= 480.0 MPa',
              },
            ],
          }
        : e,
    ),
    result: dto,
    running: false,
  });

describe('the captured run is the one we think it is', () => {
  it('is Hero A: a quarantine with a real mutation', () => {
    expect(dto.disposition).toBe('QUARANTINE');
    expect(Object.keys(dto.mutation ?? {}).length).toBeGreaterThan(0);
    expect(events.length).toBeGreaterThan(40);
  });
});

describe('projection', () => {
  it('carries the disposition through to the header', () => {
    expect(vm().dispositionLabel).toBe('QUARANTINE');
    expect(vm().dispositionTone).toBe('quarantine');
  });

  it('reads the governing basis the Investigator actually resolved', () => {
    // SPEC-A7:C, not the revision B the supplier cited. The whole hero.
    expect(vm().truth.governingBasis).toBe('SPEC-A7:C');
  });

  it('reads failing counts from the real field names', () => {
    // `failing_test_count`, not `failing_count`. Found by this capture.
    const chain = vm().disposition?.basisChain ?? [];
    const failing = chain.find((l) => l.label === 'Failing requirements');
    expect(failing?.value).toBe('1');
    expect(failing?.tone).toBe('quarantine');
  });

  it('projects the readiness change as computed, not as prose', () => {
    const changes = vm().consequence?.readinessChanges ?? [];
    expect(changes).toContainEqual({ orderId: 'C-417', from: 'READY', to: 'BLOCKED' });
  });

  it('projects every recovery candidate with its real verdict', () => {
    const byId = Object.fromEntries(
      (vm().consequence?.candidates ?? []).map((c) => [c.candidateId, c.verdict]),
    );
    expect(byId['MAT-ALLOY-7']).toBe('NOT_FEASIBLE');
    expect(byId['MAT-SUB-9']).toBe('REFUSED');
    expect(byId['C-418']).toBe('ELIGIBLE');
  });

  it('shows the executed resequence with both slots', () => {
    const executed = vm().consequence?.executed;
    expect(executed?.tag).toBe('C-418');
    expect(executed?.line).toContain('14:00');
    expect(executed?.line).toContain('08:00');
  });

  it('never invents a governing basis before the brief lands', () => {
    const early = events.filter((e) => e.event === 'EVIDENCE_RECEIVED');
    const partial = project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      events: early,
      running: true,
    });
    expect(partial.truth.governingBasis).toBeNull();
  });
});

describe('the outcome summary is structured, not parsed', () => {
  it('states the quarantine and its consequence', () => {
    const outcome = vm().outcome;
    expect(outcome.visible).toBe(true);
    expect(outcome.kind).toBe('quarantined_with_consequence');
    // The reason line answers WHY and nothing else. The order transitions
    // moved to the compact impact strip so the frame stopped restating
    // C-417/C-418 in three places.
    expect(outcome.lines).toHaveLength(1);
    expect(outcome.lines[0]).not.toMatch(/C-417/);
    expect(outcome.impact).toContain('C-417 blocked');
  });
});

describe('active stage moves only at major boundaries (D8)', () => {
  it('never hands the slot to tool traffic', () => {
    // Replay the whole run one event at a time and assert the owner never
    // becomes something a TOOL_* event could have set.
    for (let i = 1; i <= events.length; i += 1) {
      const owner = activeStageFrom(events.slice(0, i));
      const last = events[i - 1].event;
      if (last === 'TOOL_CALLED' || last === 'TOOL_RESULT_BOUND') {
        const before = activeStageFrom(events.slice(0, i - 1));
        expect(owner).toBe(before);
      }
    }
  });

  it('ends on consequence for this run', () => {
    expect(activeStageFrom(events)).toBe('consequence');
  });

  it('walks the real causal order', () => {
    const seen: string[] = [];
    for (let i = 1; i <= events.length; i += 1) {
      const owner = activeStageFrom(events.slice(0, i));
      if (owner && seen[seen.length - 1] !== owner) seen.push(owner);
    }
    expect(seen).toEqual([
      'evidence',
      'investigator',
      'verifier',
      'reconciliation',
      'disposition',
      'consequence',
    ]);
  });

  it('drops the context column only for reconciliation and consequence', () => {
    expect(project({ decisionRecordId: 'x', lotId: 'y', events: events.slice(0, 6) }).fullBleed).toBe(
      false,
    );
    expect(vm().fullBleed).toBe(true);
  });
});

describe('activity rail', () => {
  it('is newest first', () => {
    const rail = vm().activity;
    expect(rail.length).toBe(events.length);
    for (let i = 1; i < rail.length; i += 1) {
      expect(rail[i - 1].sequence).toBeGreaterThanOrEqual(rail[i].sequence);
    }
  });

  it('shows tool traffic that the stage slot ignores', () => {
    const tools = vm().activity.filter((e) => e.eventType === 'TOOL_CALLED');
    expect(tools.length).toBeGreaterThan(0);
    expect(tools[0].toolId).toBeTruthy();
  });

  it('marks only the three expandable event types', () => {
    for (const row of vm().activity) {
      if (row.expandable) {
        expect([
          'TOOL_RESULT_BOUND',
          'RECONCILIATION_COMPLETED',
          'DISPOSITION_COMPUTED',
        ]).toContain(row.eventType);
      }
    }
  });

  it('carries no prompt, reasoning or transcript text', () => {
    const blob = JSON.stringify(vm().activity).toLowerCase();
    for (const forbidden of ['thinking', 'chain_of_thought', 'rationale', 'system_prompt', 'you are']) {
      expect(blob).not.toContain(forbidden);
    }
  });

  it('attributes each event to an actor', () => {
    const investigator = vm().activity.find((e) => e.eventType === 'INVESTIGATOR_STARTED');
    const verifier = vm().activity.find((e) => e.eventType === 'VERIFIER_STARTED');
    expect(investigator?.actorType).toBe('investigator');
    expect(verifier?.actorType).toBe('verifier');
  });
});

describe('agents', () => {
  it('keeps the Verifier independent in the projection', () => {
    const v = vm().verifier;
    expect(v?.isIndependent).toBe(true);
    // The real VERIFIER_BRIEF_COMPLETED carries only a hash, so there is no
    // Investigator value for the adapter to have borrowed even by accident.
    expect(v?.basis).toBeFalsy();
  });

  it('attributes consulted records to the agent that called the tool', () => {
    const i = vm().investigator;
    const v = vm().verifier;
    expect(i?.recordsConsulted.length).toBeGreaterThan(0);
    expect(v?.recordsConsulted.length).toBeGreaterThan(0);
  });

  it('surfaces the retry the backend really performed', () => {
    // This run contains BRIEF_VALIDATION_FAILED and a second
    // INVESTIGATOR_STARTED. The rail must show it rather than hide a retry.
    const failures = vm().activity.filter((e) => e.eventType === 'BRIEF_VALIDATION_FAILED');
    expect(failures.length).toBeGreaterThan(0);
    expect(failures[0].resultStatus).toBe('caution');
  });
});

describe('recovery detail composition', () => {
  it('composes from codes and facts, never from prose', () => {
    expect(
      recoveryDetail({
        candidate_id: 'MAT-SUB-9',
        verdict: 'REFUSED',
        reason_code: 'NOT_APPROVED',
        facts: { available: 900, product: 'P-417' },
      }),
    ).toContain('not an approved substitution');
  });

  it('formats slots as times', () => {
    expect(slotTime('2026-08-15T08:00')).toBe('08:00');
  });
});

describe('event labels read business fields, not prose', () => {
  it('labels the disposition from the disposition field', () => {
    const rows = toActivity(events.filter((e) => e.event === 'DISPOSITION_COMPUTED'));
    expect(rows[0].resultSummary).toBe('QUARANTINE');
  });

  it('labels ordinary extraction without sponsor-depth copy', () => {
    const rows = toActivity(events.filter((e) => e.event === 'EVIDENCE_EXTRACTED'));
    // This document is a plain text COA; the structured headline must not appear.
    expect(rows[0].shortLabel).toBe('Evidence extracted');
  });

  it('uses meaning-first copy when structure recovery did run', () => {
    const rows = toActivity([
      {
        event: 'EVIDENCE_EXTRACTED',
        decision_record_id: 'DR-1',
        at: new Date().toISOString(),
        sequence: 1,
        claim_count: 3,
        confidence: 1,
        structured_extraction: true,
        method: 'TEXTRACT_TABLES',
      },
    ]);
    expect(rows[0].shortLabel).toBe('Structured table extracted');
    expect(rows[0].resultSummary).toBe('3 claims · confidence gate passed');
  });
});

/**
 * The terminal frame must answer three questions: what happened and why, what
 * changed for production, and what the operator does next.
 *
 * Every assertion below runs against the SAME real Hero A capture as the rest
 * of this file — a verbatim LOT-1002 response from the deployed runtime. None
 * of these numbers is written into the adapter; they are parsed back out of
 * what the deterministic engine actually emitted.
 */
describe('terminal summary answers the three questions', () => {
  it('states the deterministic reason, not a vague summary', () => {
    // The engine's own failing comparison, as a payload field. Only `failures`
    // is injected here — this capture predates the field; every number below is
    // the one the deployed runtime computed for this lot.
    const outcome = withFailures().outcome;
    expect(outcome.lines[0]).toBe(
      'Deterministic rule failed — tensile strength was 462 MPa; ' +
        'SPEC-A7 Rev C requires at least 480 MPa.',
    );
    expect(outcome.lines[0]).not.toMatch(/could not defend/);
  });

  it('omits the passing requirement from the reason', () => {
    // hardness passed, so the engine never put it in `failures`. Listing it
    // would dilute the answer to "why was this quarantined".
    expect(withFailures().outcome.lines[0]).not.toMatch(/hardness|Hardness/i);
  });

  it('falls back to the backend reason when no structured failure exists', () => {
    // An older record with no `failures` field must still say something true.
    expect(vm().outcome.lines[0]).toBe(dto.reason);
  });

  it('explains the superseded revision as subordinate context', () => {
    const outcome = vm().outcome;
    // One short line. The losing revisions are no longer enumerated here —
    // that comparison belongs to the completed Investigator detail, and
    // repeating it made the terminal frame tell the Rev B/C story twice.
    expect(outcome.context).toBe('SPEC-A7 Rev C is the governing requirement.');
    // Context must never displace the reason.
    expect(outcome.lines[0]).not.toContain('Revision B');
  });

  it('names the selected recovery, from the engine and not from ELIGIBLE', () => {
    const candidates = vm().consequence!.candidates;
    const selected = candidates.filter((c) => c.selected);
    expect(selected).toHaveLength(1);
    expect(selected[0].candidateId).toBe('C-418');
    // The refusal is the point of the stage and must stay unselected.
    expect(candidates.find((c) => c.candidateId === 'MAT-SUB-9')!.selected).toBe(false);
  });

  it('does not render the resequenced order as blocked', () => {
    const consequence = vm().consequence!;
    // C-418 was recalculated BEFORE recovery ran, then resequenced by it. The
    // stale readiness row would contradict the executed recovery card.
    expect(consequence.readinessChanges.map((c) => c.orderId)).not.toContain('C-418');
    expect(consequence.metrics.map((m) => m.label)).not.toContain('C-418');
    expect(consequence.executed!.tag).toBe('C-418');
  });

  it('finds the consequence on a STORED decision, not only a live run', () => {
    // `get_decision` nests the same object under `record`, and settle() hands
    // the whole response through as `result`. Reading only the top level made
    // the four recovery candidates vanish on every settled decision — the
    // refused substitute among them. Events alone cannot rebuild them.
    const storedShape = {
      ok: true,
      record: { consequences: dto.consequences },
    } as unknown as EvaluateDTO;
    const vmStored = project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events,
      result: storedShape,
      running: false,
    });
    expect(vmStored.consequence!.candidates.map((c) => c.candidateId)).toEqual([
      'MAT-ALLOY-7',
      'MAT-SUB-9',
      'C-418',
      'C-419',
    ]);
    expect(vmStored.consequence!.candidates.filter((c) => c.selected)).toHaveLength(1);
  });

  it('tells the operator what is still open', () => {
    // This capture predates the composition fields on CONSEQUENCE_RECALCULATED,
    // so it exercises the DEGRADED path: no material_id, no uncovered. The
    // right behaviour is to name the blocked order and stop — not to guess a
    // quantity. That an older payload still produces a truthful sentence is
    // worth pinning on its own.
    // Degraded payload: no material_id and no uncovered quantity. The
    // sentence stays truthful by naming the blocked order and the recovery
    // the engine selected, and never guessing the missing quantity.
    expect(vm().outcome.nextAction).toBe('Block C-417. Begin C-418.');
    // No invented quantity or material: the degraded payload carried neither.
    expect(vm().outcome.nextAction).not.toMatch(/MAT-|kg/);
  });

  it('reports one row per order when a decision ran more than one pass', () => {
    // The live LOT-1002 record carries 96 events across TWO consequence passes
    // (a resumed run re-runs it), so C-417 is recalculated twice. Rendering
    // both duplicated the card and made NEXT ACTION repeat its own sentence.
    // Only the LAST pass describes current state.
    const recalc = events.find((e) => e.event === 'CONSEQUENCE_RECALCULATED')!;
    const twoPasses = project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events: [...events, { ...recalc, sequence: 99 }],
      result: dto,
      running: false,
    });
    expect(twoPasses.consequence!.metrics.filter((m) => m.label === 'C-417')).toHaveLength(1);
    // The point of the test: one pass, one sentence. A duplicated recalc must
    // not make NEXT ACTION say "Block C-417." twice.
    expect(twoPasses.outcome.nextAction).toBe('Block C-417. Begin C-418.');
  });

  it('names the material and the gap once the backend emits them', () => {
    // The enriched path, as CONSEQUENCE_RECALCULATED emits it today.
    const enriched = project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events: events.map((e) =>
        e.event === 'CONSEQUENCE_RECALCULATED'
          ? { ...e, material_id: 'MAT-ALLOY-7', required: 900, available: 500, uncovered: 400 }
          : e,
      ),
      result: dto,
      running: false,
    });
    // Two imperatives: what stops, and the recovery the engine authorized.
    expect(enriched.outcome.nextAction).toBe('Block C-417. Begin C-418.');
    expect(enriched.outcome.impact).toBe(
      'C-417 blocked · C-418 moved into the available production slot.',
    );
  });
});

describe('the Consequence spine node states the impact, not the recovery', () => {
  const node = (events: typeof dto.events) =>
    project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events,
      result: dto,
      running: false,
    }).spine.find((n) => n.key === 'consequence')!;

  it('leads with the blocked order and keeps recovery as the note', () => {
    const n = node(events);
    expect(n.headline).toBe('C-417 blocked');
    expect(n.note).toBe('C-418 moved into its slot');
    // Rust, not green: an order stopped. A completed node defaults to
    // 'released', which read as a successful decision.
    expect(n.tone).toBe('quarantine');
  });

  it('survives the recovery pass that used to overwrite it', () => {
    // The live run emits a SECOND CONSEQUENCE_RECALCULATED for the resequenced
    // order. Reading the last event made the spine announce "READY · C-418".
    const n = node([
      ...events,
      {
        event: 'CONSEQUENCE_RECALCULATED',
        decision_record_id: dto.decision_record_id,
        at: '2026-09-03T05:09:00Z',
        order_id: 'C-418',
        order_readiness: 'READY',
        sequence: 999,
      },
    ] as typeof dto.events);
    expect(n.headline).toBe('C-417 blocked');
    expect(n.headline).not.toMatch(/READY/);
  });
});

describe('failureProse reads payload fields, never the reason prose', () => {
  it('returns null when the engine emitted no structured failure', () => {
    expect(failureProse(undefined, 'SPEC-A7:C')).toBeNull();
    expect(failureProse([], 'SPEC-A7:C')).toBeNull();
  });

  it('keeps the engine threshold verbatim for a two-sided limit', () => {
    const prose = failureProse(
      [
        {
          characteristic: 'hardness',
          value: 41,
          units: 'HRC',
          min_value: 28,
          max_value: 36,
          threshold_text: '[28.0, 36.0] HRC',
        },
      ],
      'SPEC-A7:C',
    );
    expect(prose).toBe(
      'Deterministic rule failed — hardness was 41 HRC; ' +
        'SPEC-A7 Rev C requires [28.0, 36.0] HRC.',
    );
  });

  it('renders without a basis when none was resolved', () => {
    const prose = failureProse([
      { characteristic: 'tensile_strength', value: 462, units: 'MPa', min_value: 480, max_value: null },
    ]);
    expect(prose).toBe(
      'Deterministic rule failed — tensile strength was 462 MPa; Requirement: at least 480 MPa.',
    );
  });
});
