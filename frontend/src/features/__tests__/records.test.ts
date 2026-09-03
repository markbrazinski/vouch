/**
 * Records, against REAL durable records fetched from the deployed runtime.
 *
 * `hero-a-record-capture.json` is a live `get_decision` for the Hero A
 * quarantine; `hero-b-record-capture.json` is the two-run Hero B case where a
 * human supplied evidence and the SAME record resumed. Presigned `view_ref`
 * values were stripped and account ids redacted before either was committed —
 * a presigned URL is a bearer credential and must not live in a repository.
 */

import { describe, expect, it } from 'vitest';
import heroA from '../../decision/__tests__/hero-a-record-capture.json';
import heroB from '../../decision/__tests__/hero-b-record-capture.json';
import { runsOf, toDecisionRecord } from '../records/model';

const a = toDecisionRecord(heroA.record as Record<string, unknown>, heroA.sources);
const b = toDecisionRecord(heroB.record as Record<string, unknown>, heroB.sources);

describe('the captures are the decisions we think they are', () => {
  it('Hero A is a single-run quarantine with a real mutation', () => {
    expect(a.disposition).toBe('QUARANTINE');
    expect(a.runCount).toBe(1);
    expect(a.mutation.occurred).toBe(true);
  });

  it('Hero B is a two-run case that ended in a release', () => {
    expect(b.disposition).toBe('RELEASE');
    expect(b.runCount).toBe(2);
  });
});

describe('identity and evidence', () => {
  it('names the lot, material and supplier from the record', () => {
    expect(a.lotId).toBe('LOT-1002');
    expect(a.materialId).toBe('MAT-ALLOY-7');
    expect(a.supplierId).toBe('SUP-EAST');
    expect(a.supplierSite).toBe('SITE-E1');
  });

  it('keeps evidence provenance: trust class, hash and version', () => {
    const [doc] = a.evidence;
    expect(doc.trustClass).toBe('UNTRUSTED_SUPPLIER');
    expect(doc.trustLabel).toBe('Supplier — untrusted');
    expect(doc.contentHash).not.toBe('');
    expect(doc.objectVersion).not.toBe('');
    expect(doc.claimCount).toBe(2);
    expect(doc.excluded).toBe(false);
  });

  it('never carries a presigned URL into the model', () => {
    expect(JSON.stringify(a)).not.toContain('X-Amz-Signature');
    expect(a.evidence.every((e) => !('viewRef' in e))).toBe(true);
  });

  it('distinguishes human-authorized evidence from supplier evidence', () => {
    const human = b.evidence.filter((e) => e.humanAuthorized);
    expect(human).toHaveLength(1);
    expect(human[0].documentIdentity).toBe('QA_RETEST');
    expect(b.evidence.filter((e) => !e.humanAuthorized)).toHaveLength(1);
  });
});

describe('runs are composed the way the backend composes them', () => {
  it('returns one run for a decision that never resumed', () => {
    expect(a.runs.map((r) => r.runNumber)).toEqual([1]);
  });

  it('returns the archived run AND the live one for a resumed decision', () => {
    // archived_runs alone is missing the current run; the live segments alone
    // are missing the history. Records needs both.
    expect(b.runs.map((r) => r.runNumber)).toEqual([1, 2]);
    expect((heroB.record as Record<string, unknown>).archived_runs).toHaveLength(1);
  });

  it('keeps run 1 as an abstention and run 2 as the release', () => {
    const [run1, run2] = b.runs;
    expect(run1.abstained).toBe(true);
    expect(run1.disposition).toBe('');
    expect(run1.failureCategory).toBe('MATERIAL_DISAGREEMENT');
    expect(run2.abstained).toBe(false);
    expect(run2.disposition).toBe('RELEASE');
  });

  it('preserves why run 1 could not conclude', () => {
    expect(b.runs[0].reconciliation.outcome).toBe('MATERIAL_DISAGREEMENT');
    expect(b.runs[0].reconciliation.agreed).toBe(false);
    expect(b.runs[0].reconciliation.differingFields).toEqual(['coverage', 'missing']);
  });

  it('treats a non-material difference as agreement', () => {
    // MATCH and NON_MATERIAL_DIFFERENCE both mean the agents agreed on
    // everything that decides the outcome.
    expect(b.runs[1].reconciliation.outcome).toBe('NON_MATERIAL_DIFFERENCE');
    expect(b.runs[1].reconciliation.agreed).toBe(true);
    expect(a.runs[0].reconciliation.outcome).toBe('MATCH');
    expect(a.runs[0].reconciliation.agreed).toBe(true);
  });
});

describe('the two agents stay independent', () => {
  it('reads each agent from its own segment', () => {
    const run = a.runs[0];
    expect(run.investigator!.role).toBe('investigator');
    expect(run.verifier!.role).toBe('verifier');
    expect(run.investigator!.modelId).toBe('us.amazon.nova-pro-v1:0');
    expect(run.verifier!.modelId).toBe('us.amazon.nova-pro-v1:0');
  });

  it('distinguishes the two agents by their own prompt version', () => {
    const run = a.runs[0];
    expect(run.investigator!.promptVersion).toBe('investigator-v2.2');
    expect(run.verifier!.promptVersion).toBe('verifier-v2.2');
  });

  it('shares a brief hash because both agents are given the SAME input', () => {
    // Verified against two live records: `brief_hash` equals
    // `input_claim_set_hash`, so it fingerprints the brief the agents were
    // HANDED, not what either concluded. Independence therefore cannot be
    // asserted from this field, and a UI must not try - it lives in the
    // per-role conclusions the reconciliation records separately.
    const run = a.runs[0];
    expect(run.verifier!.briefHash).toBe(run.investigator!.briefHash);
  });

  it('shows each agent its OWN conclusion when they disagreed', () => {
    // Run 1: the investigator found viscosity covered, the verifier found it
    // missing. Showing one agent's answer in both columns would erase the
    // independence the architecture exists to prove.
    const run1 = b.runs[0];
    expect(run1.investigator!.covered).toEqual(['viscosity']);
    expect(run1.investigator!.missing).toEqual([]);
    expect(run1.verifier!.covered).toEqual([]);
    expect(run1.verifier!.missing).toEqual(['viscosity']);
  });
});

describe('mutation is reported only when one happened', () => {
  it('reports the real quarantine with its version change and ledger entry', () => {
    expect(a.mutation.action).toBe('quarantine_lot');
    expect(a.mutation.targetId).toBe('LOT-1002');
    expect(a.mutation.versionChange).toBe('v1 → v2');
    expect(a.mutation.result).toBe('lot LOT-1002 QUARANTINED');
    expect(a.mutation.ledgerSequence).not.toBe('');
  });

  it('reports no state change when nothing mutated', () => {
    const none = toDecisionRecord({ record_id: 'DR-x', disposition: { disposition: '' } });
    expect(none.mutation.occurred).toBe(false);
    expect(none.mutation.result).toBe('');
  });
});

describe('human continuation is evidence, not approval', () => {
  it('records who was accountable, from the record and not a UI constant', () => {
    expect(b.human.occurred).toBe(true);
    expect(b.human.authoritySource).toBe('QA-LEAD');
    expect(b.human.evidenceSupplied).toHaveLength(1);
    expect(b.human.resumedRunIds).toEqual(['DR-b814ea2ca1de#run2']);
  });

  it('reports no continuation for a decision no human touched', () => {
    expect(a.human.occurred).toBe(false);
    expect(a.human.authoritySource).toBe('');
  });

  it('keeps the same record id across both runs', () => {
    expect(b.recordId).toBe('DR-b814ea2ca1de');
    expect(b.human.resumedRunIds[0].startsWith(b.recordId)).toBe(true);
  });
});

describe('operational consequence', () => {
  it('carries the readiness change the quarantine caused', () => {
    expect(a.consequence.readinessChanges).toEqual([
      {
        orderId: 'C-417',
        from: 'READY',
        to: 'BLOCKED',
        reason: 'MAT-ALLOY-7 short by 900.0 (need 900.0, have 0)',
      },
    ]);
  });

  it('keeps the refused substitute refused', () => {
    const sub = a.consequence.recoveryCandidates.find((c) => c.candidateId === 'MAT-SUB-9')!;
    expect(sub.verdict).toBe('REFUSED');
    expect(sub.reasonCode).toBe('NOT_APPROVED');
  });

  it('does not present the blocked order as repaired', () => {
    // C-418 is the eligible resequence. C-417 stays blocked, and nothing in
    // the projection says otherwise.
    expect(a.consequence.blockedOrderId).toBe('C-417');
    const eligible = a.consequence.recoveryCandidates.filter((c) => c.verdict === 'ELIGIBLE');
    expect(eligible.every((c) => c.candidateId !== 'C-417')).toBe(true);
  });
});

describe('a malformed or empty record does not crash the surface', () => {
  it('projects an empty record without inventing anything', () => {
    const empty = toDecisionRecord({});
    expect(empty.disposition).toBe('');
    expect(empty.evidence).toEqual([]);
    expect(empty.mutation.occurred).toBe(false);
    expect(empty.human.occurred).toBe(false);
    expect(empty.runs).toHaveLength(1);
  });

  it('still yields one run when the record has no archived runs field', () => {
    expect(runsOf({ run_count: 1 })).toHaveLength(1);
  });
});
