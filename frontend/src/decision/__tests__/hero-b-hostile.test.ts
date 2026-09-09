/**
 * Hero B and Hostile, against REAL captured backend responses.
 *
 * Same discipline as `adapter.test.ts`: these three files are verbatim
 * AgentCore responses from the deployed runtime, not hand-written fixtures.
 *
 *   hero-b-run1  ambiguous evidence -> MATERIAL_DISAGREEMENT, Quality asked
 *   hero-b-run2  QA retest -> SAME record, run_count 2 -> RELEASE
 *   hostile      injection payload -> SECURITY_QUARANTINE, agents never ran
 *
 * The question this gate asks is whether the EXISTING Decision Workspace
 * generalizes to them, so nothing here is Hero-specific machinery.
 */

import { describe, expect, it } from 'vitest';
import run1 from './hero-b-run1-capture.json';
import run2 from './hero-b-run2-capture.json';
import hostile from './hostile-capture.json';
import { project, toActivity } from '../adapter';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';

const vmOf = (capture: unknown, lotId: string, running = false) => {
  const dto = capture as EvaluateDTO;
  return project({
    decisionRecordId: dto.decision_record_id,
    lotId,
    material: 'MAT-POLY-3',
    receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    events: (dto.events ?? []) as LifecycleEventDTO[],
    result: dto,
    running,
  });
};

describe('the captures are the runs we think they are', () => {
  it('Hero B run 1 asked Quality and released nothing', () => {
    const dto = run1 as EvaluateDTO;
    expect(dto.quality_decision_required).toBe(true);
    expect(dto.disposition).toBe('');
    expect(Object.keys(dto.mutation ?? {})).toHaveLength(0);
  });

  it('Hero B run 2 is the SAME record, continued', () => {
    expect((run2 as EvaluateDTO).decision_record_id).toBe(
      (run1 as EvaluateDTO).decision_record_id,
    );
    expect((run2 as EvaluateDTO).disposition).toBe('RELEASE');
  });

  it('the hostile document never reached an agent', () => {
    const events = ((hostile as EvaluateDTO).events ?? []) as LifecycleEventDTO[];
    expect(events.map((e) => e.event)).not.toContain('INVESTIGATOR_STARTED');
    expect(Object.keys((hostile as EvaluateDTO).mutation ?? {})).toHaveLength(0);
  });
});

describe('Hero B run 1 — Vouch asks a human', () => {
  const vm = () => vmOf(run1, 'LOT-1003');

  it('renders quality-decision-required, not a crash', () => {
    expect(vm().outcome.kind).toBe('quality_decision_required');
    expect(vm().outcome.visible).toBe(true);
  });

  it('shows no disposition, because none exists', () => {
    expect(vm().disposition?.disposition ?? '').not.toBe('RELEASE');
  });

  it('is a domain abstention, never a technical failure', () => {
    expect(vm().failure?.kind).not.toBe('TECHNICAL_FAILURE');
  });

  it('surfaces the material disagreement between the two agents', () => {
    expect(vm().reconciliation?.state).toBe('MATERIAL_DISAGREEMENT');
  });

  it('still renders both agent lanes', () => {
    expect(vm().investigator).not.toBeNull();
    expect(vm().verifier).not.toBeNull();
  });
});

describe('Hero B run 2 — the human evidence resumes the same record', () => {
  const vm = () => vmOf(run2, 'LOT-1003');

  it('reaches RELEASE with a real mutation', () => {
    expect(vm().dispositionLabel).toBe('RELEASE');
    expect(vm().disposition?.stateMutation.length).toBeGreaterThan(0);
  });

  it('shows the human continuation in the activity rail', () => {
    const types = vm().activity.map((a) => a.eventType);
    expect(types).toContain('HUMAN_EVIDENCE_RECEIVED');
    expect(types).toContain('DECISION_RESUMED');
  });

  it('attributes the supplied evidence to a human actor', () => {
    const human = vm().activity.find((a) => a.eventType === 'HUMAN_EVIDENCE_RECEIVED');
    expect(human?.actorType).toBe('human');
  });

  it('attributes the agent stages to run 2, matching the rail', () => {
    // The "RUN 2" badge reads `runNumber` off the agent stage, which took it
    // from `started.run_number` — a field the backend never sends. It reported
    // run 1 on a run-2 decision while the rail said run 2.
    expect(vm().investigator?.runNumber).toBe(2);
    expect(vm().verifier?.runNumber).toBe(2);
  });

  it('no longer asks for a quality decision', () => {
    expect(vm().outcome.kind).toBe('released');
  });

  it('distinguishes run 2 from run 1', () => {
    const resumed = vm().activity.find((a) => a.eventType === 'DECISION_RESUMED');
    expect(resumed?.runNumber).toBe(2);
  });

  it('files the human act itself under the run it opens, not the one it ended', () => {
    const human = vm().activity.find((a) => a.eventType === 'HUMAN_EVIDENCE_RECEIVED');
    expect(human?.runNumber).toBe(2);
  });
});

describe('the full record history, as get_events returns it', () => {
  // Both runs concatenated: what a client polling one record actually holds.
  const both = [
    ...(((run1 as EvaluateDTO).events ?? []) as LifecycleEventDTO[]),
    ...(((run2 as EvaluateDTO).events ?? []) as LifecycleEventDTO[]),
  ];

  it('splits one continuous stream into two runs at the human boundary', () => {
    const runs = new Set(toActivity(both).map((a) => a.runNumber));
    expect([...runs].sort()).toEqual([1, 2]);
  });

  it('keeps everything before the human evidence in run 1', () => {
    const acts = toActivity(both);
    const boundary = acts.findIndex((a) => a.eventType === 'HUMAN_EVIDENCE_RECEIVED');
    expect(boundary).toBeGreaterThan(0);
    expect(acts.slice(0, boundary).every((a) => a.runNumber === 1)).toBe(true);
    expect(acts.slice(boundary).every((a) => a.runNumber === 2)).toBe(true);
  });

  it('never regresses a run number as the stream advances', () => {
    const nums = toActivity(both).map((a) => a.runNumber);
    expect(nums).toEqual([...nums].sort((a, b) => a - b));
  });

  it('honours an explicit run_number if the backend ever sends one', () => {
    const tagged = toActivity([
      { event: 'EVIDENCE_RECEIVED', run_number: 7 } as unknown as LifecycleEventDTO,
    ]);
    expect(tagged[0].runNumber).toBe(7);
  });
});

describe('Hostile — security halts the spine before any agent starts', () => {
  const vm = () => vmOf(hostile, 'LOT-1004');

  it('renders the security hold as its own outcome', () => {
    expect(vm().outcome.kind).toBe('evidence_quarantined');
  });

  it('never renders a disposition', () => {
    expect(vm().dispositionLabel).not.toBe('RELEASE');
    expect(vm().disposition).toBeNull();
  });

  it('renders NO agent placeholders — contract invariant 6', () => {
    expect(vm().investigator).toBeNull();
    expect(vm().verifier).toBeNull();
    expect(vm().reconciliation).toBeNull();
  });

  it('halts the spine rather than leaving it pending', () => {
    const agents = vm().spine.find((n) => n.key === 'agents');
    expect(agents?.state).toBe('halted');
  });

  it('reports zero mutation', () => {
    expect(vm().consequence?.executed ?? null).toBeNull();
  });

  it('binds the LOT, not the word "BOUND" — the column has that heading already', () => {
    // Pre-existing: `binding_status` under a "BOUND FACT" label rendered
    // "BOUND FACT: BOUND". Hero A's terminal frame is full-bleed so its case
    // column is hidden; the hostile path keeps the column and exposed it.
    expect(vm().truth.boundFact?.value).toBe('LOT-1004');
  });

  it('shows the guardrail detection in the rail', () => {
    const sec = toActivity(((hostile as EvaluateDTO).events ?? []) as LifecycleEventDTO[])
      .find((a) => a.eventType === 'EVIDENCE_SECURITY_COMPLETED');
    expect(sec?.actorType).toBe('security');
    expect(sec?.resultStatus).toBe('bad');
  });
});

describe('the halted spine reads as stopped, not as still-coming', () => {
  const vm = () => vmOf(hostile, 'LOT-1004');

  it('marks the disposition node halted rather than pending', () => {
    expect(vm().spine.find((n) => n.key === 'disposition')?.state).toBe('halted');
  });

  it('says the agents never started', () => {
    expect(vm().spine.find((n) => n.key === 'agents')?.headline).toBe('Not started');
  });

  it('seals reconciliation as halted, never as a match', () => {
    expect(vm().spine.find((n) => n.key === 'agents')?.reconciliationSeal).toBe('halted');
  });

  it('states NO MUTATION rather than leaving consequence pending', () => {
    // A halted decision has nothing downstream still coming. "Pending" there
    // forecasts a state change that will never arrive.
    const consequence = vm().spine.find((n) => n.key === 'consequence');
    expect(consequence?.state).toBe('halted');
    expect(consequence?.headline).toBe('No mutation');
  });

  it('renders no PENDING node anywhere downstream of the halt', () => {
    expect(vm().spine.map((n) => n.state)).not.toContain('pending');
  });

  it('names the evidence node for what was found in it', () => {
    expect(vm().spine.find((n) => n.key === 'evidence')?.headline).toBe('Prompt injection');
  });

  it('says NONE for disposition, never a weak verdict', () => {
    expect(vm().spine.find((n) => n.key === 'disposition')?.headline).toBe('None');
  });

  it('states NOT_STARTED in both agent lanes, not the unknown em-dash', () => {
    // The em-dash means "not known yet". These agents are never going to run,
    // which is a different fact and the one the operator has to read.
    const agents = vm().spine.find((n) => n.key === 'agents');
    expect(agents?.investigatorLane).toBe('NOT_STARTED');
    expect(agents?.verifierLane).toBe('NOT_STARTED');
  });

  it('gives every halted node its own tone so it renders its own headline', () => {
    // Without an explicit tone `nodePill` collapses all of them to "⊘ HALTED",
    // which tells the operator nothing about which stage stopped.
    for (const key of ['evidence', 'agents', 'disposition', 'consequence']) {
      expect(vm().spine.find((n) => n.key === key)?.tone).toBe('quarantine');
    }
  });
});

describe('the detection is attributed to Amazon Bedrock Guardrails', () => {
  const vm = () => vmOf(hostile, 'LOT-1004');
  const rail = () =>
    toActivity(((hostile as EvaluateDTO).events ?? []) as LifecycleEventDTO[]);

  it('leads the terminal summary with the attack, not a generic hold', () => {
    expect(vm().outcome.headline).toBe('Prompt injection detected');
  });

  it('names the AWS service that actually made the detection', () => {
    expect(vm().outcome.lines[0]).toContain('Amazon Bedrock Guardrails');
  });

  it('states that neither agent saw the document', () => {
    expect(vm().outcome.lines[0]).toContain('before it reached either decision agent');
  });

  it('states that nothing was decided and nothing changed', () => {
    expect(vm().outcome.lines[1]).toBe('No disposition was made. No production state changed.');
  });

  it('chips it as a security quarantine', () => {
    expect(vm().outcome.chip?.label).toBe('SECURITY QUARANTINE');
  });

  it('never credits the detection to an agent, a model, or Model Armor', () => {
    // Model Armor is not the AWS service, and neither agent ran at all.
    const text = [vm().outcome.headline, ...vm().outcome.lines, ...rail().flatMap((r) => [r.shortLabel, r.resultSummary ?? ''])].join(' ');
    for (const wrong of ['Model Armor', 'Investigator', 'Verifier', 'Nova']) {
      expect(text).not.toContain(wrong);
    }
  });

  it('names Guardrails on the security row in the rail', () => {
    const sec = rail().find((a) => a.eventType === 'EVIDENCE_SECURITY_COMPLETED');
    expect(sec?.shortLabel).toBe('Prompt injection detected');
    expect(sec?.resultSummary).toBe('Amazon Bedrock Guardrails');
  });

  it('never claims a Quality decision on a branch that has no Quality authority', () => {
    // The backend routes every non-autonomous exit through the same
    // QUALITY_DECISION_REQUIRED event, so the raw label asserted a Quality
    // decision that does not exist on a security halt.
    const qdr = rail().find((a) => a.eventType === 'QUALITY_DECISION_REQUIRED');
    expect(qdr?.shortLabel).toBe('Decision halted before agent reasoning');
    expect(qdr?.shortLabel).not.toContain('Quality');
    expect(qdr?.resultStatus).toBe('bad');
  });

  it('attributes the halt to Vouch, never to Quality', () => {
    const qdr = rail().find((a) => a.eventType === 'QUALITY_DECISION_REQUIRED');
    expect(qdr?.actorDisplayName).toBe('Vouch');
  });

  it('does not narrate binding as if processing continued past the halt', () => {
    const binding = rail().find((a) => a.eventType === 'EVIDENCE_BINDING_COMPLETED');
    expect(binding?.shortLabel).toBe('Evidence quarantined');
    expect(binding?.actorDisplayName).toBe('Vouch');
  });

  it('never echoes the hostile payload into the rail', () => {
    // The artifact viewer is where hostile content is inspected deliberately.
    // The rail is read over someone's shoulder.
    const text = rail()
      .flatMap((r) => [r.shortLabel, r.resultSummary ?? '', ...(r.detail ?? []).map((d) => d.value)])
      .join(' ');
    for (const fragment of ['IGNORE ALL PREVIOUS', 'release_lot', 'Revision B']) {
      expect(text).not.toContain(fragment);
    }
  });

  it('emits no Investigator or Verifier row after the halt', () => {
    expect(rail().every((r) => r.actorType !== 'investigator' && r.actorType !== 'verifier')).toBe(
      true,
    );
  });
});

describe('Hero A is unaffected by the halted-path changes', () => {
  it('still resolves a real bound identity', () => {
    const dto = run2 as EvaluateDTO;
    const events = (dto.events ?? []) as LifecycleEventDTO[];
    const projected = project({
      decisionRecordId: dto.decision_record_id,
      lotId: 'LOT-1003',
      material: 'MAT-POLY-3',
      receiptMeta: '',
      events,
      result: dto,
      running: false,
    });
    expect(projected.truth.boundFact?.value).toBe('LOT-1003');
    expect(projected.spine.find((n) => n.key === 'agents')?.state).not.toBe('halted');
  });
});

describe('the verifier lane reads the VERIFIER\'s own brief', () => {
  /**
   * RESOLVED: FE_ADAPTER_FIX, not a read-model gap.
   *
   * The verifier's completion EVENT carries only `brief_hash` — `agents.py`
   * puts `sufficiency` in the payload for the investigator alone. But
   * `AgentSegment.brief` persists the COMPLETE brief for both agents, and
   * `get_decision` returns it at `record.verifier.brief.sufficiency`
   * (confirmed live on DR-b814ea2ca1de). The data existed; the adapter was
   * reading the wrong source.
   *
   * The value is taken strictly per-role. A lane that borrowed the
   * investigator's answer would make an independent verifier look like it
   * agreed when it was never asked — which is the whole product.
   */
  const record = {
    investigator: { brief: { sufficiency: 'SUFFICIENT' } },
    verifier: { brief: { sufficiency: 'INSUFFICIENT_EVIDENCE' } },
  };

  const withRecord = (rec: Record<string, unknown> | null) => {
    const dto = run1 as EvaluateDTO;
    return project({
      decisionRecordId: dto.decision_record_id,
      lotId: 'LOT-1003',
      material: 'MAT-POLY-3',
      receiptMeta: '',
      events: (dto.events ?? []) as LifecycleEventDTO[],
      result: dto,
      record: rec,
      running: false,
    });
  };

  it('fills the verifier lane from the stored record', () => {
    const agents = withRecord(record).spine.find((n) => n.key === 'agents');
    expect(agents?.verifierLane).toBe('INSUFFICIENT_EVIDENCE');
  });

  it('never lets the verifier lane borrow the investigator value', () => {
    // The two disagree here on purpose: if the lane ever shows the actor's
    // answer, independence is being faked in the UI.
    const agents = withRecord({
      investigator: { brief: { sufficiency: 'SUFFICIENT' } },
      verifier: {},
    }).spine.find((n) => n.key === 'agents');
    expect(agents?.verifierLane ?? null).toBeNull();
  });

  it('stays null before the record lands, rather than guessing', () => {
    const agents = withRecord(null).spine.find((n) => n.key === 'agents');
    expect(agents?.verifierLane ?? null).toBeNull();
    expect(agents?.investigatorLane).toBe('INSUFFICIENT_EVIDENCE');
  });

  it('still proves independence through reconciliation, which IS populated', () => {
    expect(vmOf(run1, 'LOT-1003').reconciliation?.state).toBe('MATERIAL_DISAGREEMENT');
  });
});
