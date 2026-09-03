/**
 * Event ingestion.
 *
 * The poll and the terminal response both deliver events and WILL overlap, so
 * re-delivery has to be free.
 *
 * Dedupe is by event IDENTITY (type + timestamp + payload), NOT by sequence or
 * event_id. Live traffic settled that: the backend deliberately writes each
 * event twice — once live from the sink, once in the terminal batch — and the
 * two copies carry different sequences and different ids. A 38-event run polls
 * back as 98 rows.
 */

import { describe, expect, it } from 'vitest';
import { classifyFailure, mergeEvents } from '../useDecisionRun';
import { TransportError } from '../../adapter/client';
import type { LifecycleEventDTO } from '../dto';

/**
 * A distinct event. `at` is what makes two rows genuinely different — the
 * backend sets it once at construction, so the same emitted event always
 * carries the same instant no matter how many times it is written.
 */
const e = (sequence: number, event = 'TOOL_CALLED', at = `2026-09-03T05:00:${String(sequence).padStart(2, '0')}Z`): LifecycleEventDTO => ({
  event,
  decision_record_id: 'DR-1',
  at,
  sequence,
});

describe('mergeEvents', () => {
  it('keeps ascending order', () => {
    const merged = mergeEvents([e(1), e(2)], [e(4), e(3)]);
    expect(merged.map((x) => x.at)).toEqual([
      '2026-09-03T05:00:01Z',
      '2026-09-03T05:00:02Z',
      '2026-09-03T05:00:03Z',
      '2026-09-03T05:00:04Z',
    ]);
  });

  it('dedupes re-delivered events', () => {
    const merged = mergeEvents([e(1), e(2), e(3)], [e(2), e(3), e(4)]);
    expect(merged).toHaveLength(4);
  });

  it('is idempotent', () => {
    const once = mergeEvents([], [e(1), e(2)]);
    expect(mergeEvents(once, [e(1), e(2)])).toHaveLength(2);
  });

  it('does not drop existing events when nothing new arrives', () => {
    const existing = [e(1), e(2)];
    expect(mergeEvents(existing, [])).toBe(existing);
  });

  it('handles a batch arriving out of order', () => {
    const merged = mergeEvents([], [e(9), e(1), e(5)]);
    expect(merged.map((x) => x.at)).toEqual([
      '2026-09-03T05:00:01Z',
      '2026-09-03T05:00:05Z',
      '2026-09-03T05:00:09Z',
    ]);
  });

  it('collapses the backend double-write', () => {
    // THE bug live traffic found. The backend writes each event twice — once
    // live from the sink, once in the terminal batch — with DIFFERENT sequence
    // numbers and different event_ids. A 2-event run polls back as 4 rows.
    // Deduping on sequence or id would show the rail twice over.
    const live = { ...e(1, 'INVESTIGATOR_STARTED'), event_id: 'DR-1#000001' };
    const batched = { ...e(3, 'INVESTIGATOR_STARTED', live.at), event_id: 'DR-1#000003' };
    const merged = mergeEvents([], [live, batched]);
    expect(merged).toHaveLength(1);
  });

  it('keeps two genuinely distinct tool calls apart', () => {
    // The flip side: identical event TYPE is not identical event. Two
    // TOOL_CALLED rows at different instants are two real tool calls.
    const merged = mergeEvents(
      [],
      [
        { ...e(1, 'TOOL_CALLED', '2026-09-03T05:00:01Z'), tool: 'list_candidate_specs' },
        { ...e(2, 'TOOL_CALLED', '2026-09-03T05:00:02Z'), tool: 'get_spec_requirement' },
      ],
    );
    expect(merged).toHaveLength(2);
  });

  it('flattens the payload the poll path nests', () => {
    // get_events returns { event, sequence, at, payload:{...} } while evaluate
    // returns the fields flat. The adapter must see one shape.
    const merged = mergeEvents(
      [],
      [
        {
          event: 'DISPOSITION_COMPUTED',
          decision_record_id: 'DR-1',
          at: '2026-09-03T05:00:09Z',
          sequence: 9,
          payload: { disposition: 'QUARANTINE', basis: 'SPEC-A7:C' },
        } as unknown as LifecycleEventDTO,
      ],
    );
    expect(merged[0].disposition).toBe('QUARANTINE');
    expect(merged[0].basis).toBe('SPEC-A7:C');
  });

  it('renumbers densely so every row has a stable unique key', () => {
    // Duplicate React keys were the visible symptom of all of the above.
    const merged = mergeEvents([], [e(7), e(2), e(90)]);
    expect(merged.map((x) => x.sequence)).toEqual([1, 2, 3]);
    expect(new Set(merged.map((x) => x.sequence)).size).toBe(merged.length);
  });
});

describe('failure classification', () => {
  it('treats a transport failure as technical and suppresses any disposition', () => {
    const f = classifyFailure(new TransportError('boom', 0));
    expect(f.kind).toBe('TECHNICAL_FAILURE');
    expect(f.suppressesDisposition).toBe(true);
    // The copy must not imply anything about the material.
    expect(f.detail).toContain('Nothing about this lot has changed');
  });

  it('treats a persistence failure as technical, not as a verdict', () => {
    const f = classifyFailure({
      ok: false,
      failure_category: 'PERSISTENCE_FAILURE',
      error: 'could not list decisions',
    });
    expect(f.kind).toBe('TECHNICAL_FAILURE');
    expect(f.suppressesDisposition).toBe(true);
  });

  it('treats an abstention as a domain outcome, not a crash', () => {
    const f = classifyFailure({ ok: false, failure_category: 'EXTRACTION_LOW_CONFIDENCE' });
    expect(f.kind).toBe('DOMAIN_ABSTENTION');
    expect(f.suppressesDisposition).toBe(false);
  });

  it('distinguishes a security hold from both', () => {
    const f = classifyFailure({ ok: false, failure_category: 'SECURITY_QUARANTINE' });
    expect(f.kind).toBe('SECURITY_HOLD');
    expect(f.suppressesDisposition).toBe(false);
  });

  it('distinguishes a stale-state conflict', () => {
    const f = classifyFailure({ ok: false, failure_category: 'STATE_CONFLICT' });
    expect(f.kind).toBe('CONFLICT_STALE');
    expect(f.suppressesDisposition).toBe(true);
  });

  it('distinguishes a policy refusal', () => {
    const f = classifyFailure({ ok: false, failure_category: 'POLICY_REFUSAL' });
    expect(f.kind).toBe('POLICY_REFUSAL');
  });

  it('never returns a disposition for any failure', () => {
    for (const category of [
      'PERSISTENCE_FAILURE',
      'MODEL_UNAVAILABLE',
      'TOOL_FAILURE',
      'SCHEMA_FAILURE',
      'SECURITY_QUARANTINE',
      'EXTRACTION_LOW_CONFIDENCE',
      'STATE_CONFLICT',
      'POLICY_REFUSAL',
    ]) {
      const f = classifyFailure({ ok: false, failure_category: category });
      expect(f).not.toHaveProperty('disposition');
      expect(JSON.stringify(f)).not.toMatch(/RELEASE|QUARANTINE/);
    }
  });
});
