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
import { project, toActivity, activeStageFrom, recoveryDetail, slotTime } from '../adapter';
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
    expect(outcome.lines.some((l) => l.includes('C-417') && l.includes('BLOCKED'))).toBe(true);
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
