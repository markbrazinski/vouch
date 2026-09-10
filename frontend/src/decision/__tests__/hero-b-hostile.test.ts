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
// Hero A carries the real 13.4s investigator->verifier gap this file pins.
import heroA from './hero-a-capture.json';
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
  const vm = () => vmOf(run1, 'LOT-1004');

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
  const vm = () => vmOf(run2, 'LOT-1004');

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
  const vm = () => vmOf(hostile, 'LOT-1005');

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
    //
    // LOT-1004, not LOT-1005: this reads the id out of the FROZEN capture,
    // which recorded a real execution back when the hostile fixture was
    // LOT-1004. The canonical renumber moved the scenario to LOT-1005; it did
    // not, and must not, rewrite what that run actually observed.
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
  const vm = () => vmOf(hostile, 'LOT-1005');

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
  const vm = () => vmOf(hostile, 'LOT-1005');
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
    // LOT-1003 is what this FROZEN capture observed: the disagreement run was
    // recorded under that id and the renumber left the bytes alone. It happens
    // to be the scenario's final canonical id too, but the reason to write it
    // here is the capture, not the map.
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
      lotId: 'LOT-1004',
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
    expect(vmOf(run1, 'LOT-1004').reconciliation?.state).toBe('MATERIAL_DISAGREEMENT');
  });
});

/**
 * The Verifier must not appear to be filled in AFTER the outcome.
 *
 * Measured on the Hero A capture: the Investigator's brief lands at :44.201
 * and the Verifier's at :57.603 — the Verifier reasons ALONE for 13.4s — after
 * which reconciliation, disposition and consequence all land inside ~500ms.
 *
 * The backend order was never wrong. What was wrong is that the lane had no
 * value to show during those 13.4s, so it rendered the em-dash that means
 * "nothing is known" — visually identical to a stage that never ran. The
 * screen therefore looked as though verification was back-filled once the
 * disposition already existed, which inverts the product's central claim.
 *
 * VERIFIER_STARTED already establishes the missing fact, so the lane states
 * it. These tests pin the three states apart.
 */
describe('the verifier lane is populated while it reasons, before disposition', () => {
  const laneAt = (upTo: (name: string) => boolean) => {
    const dto = heroA as EvaluateDTO;
    const all = (dto.events ?? []) as LifecycleEventDTO[];
    const cut: LifecycleEventDTO[] = [];
    for (const e of all) {
      cut.push(e);
      if (upTo(String((e as Record<string, unknown>).event ?? ''))) break;
    }
    return project({
      decisionRecordId: dto.decision_record_id,
      lotId: 'LOT-1002',
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events: cut,
      result: null,
      running: true,
    }).spine.find((n) => n.key === 'agents');
  };

  it('shows IN_PROGRESS while the verifier is running and no brief exists yet', () => {
    const agents = laneAt((n) => n === 'VERIFIER_STARTED');
    expect(agents?.verifierLane).toBe('IN_PROGRESS');
    // And it is populated BEFORE any disposition exists — the whole point.
    expect(agents?.reconciliationSeal).toBe('pending');
  });

  it('shows the em-dash state before the verifier has started at all', () => {
    // Cut at the investigator's completion: the verifier has not started, so
    // "reasoning" would be a claim nothing has established.
    const agents = laneAt((n) => n === 'APPLICABILITY_BRIEF_COMPLETED');
    expect(agents?.verifierLane ?? null).toBeNull();
  });

  it('stops claiming the verifier is reasoning once its brief lands', () => {
    // This capture PREDATES the change that made both roles publish
    // `sufficiency`: its VERIFIER_BRIEF_COMPLETED carries only `brief_hash`,
    // and no record is passed here. The lane therefore returns to "not known
    // yet" rather than to a finding — what must NOT survive is the claim that
    // the agent is still working.
    //
    // Historical captures replaying this way is the reason `briefSufficiency`
    // still exists. A live run resolves this lane from the event itself; see
    // the "resolves before any record" suite below.
    const agents = laneAt((n) => n === 'VERIFIER_BRIEF_COMPLETED');
    expect(agents?.verifierLane ?? null).toBeNull();
  });

  it('never claims a halted verifier is reasoning', () => {
    const agents = vmOf(hostile, 'LOT-1005').spine.find((n) => n.key === 'agents');
    expect(agents?.verifierLane).toBe('NOT_STARTED');
  });
});

/**
 * The Verifier lane resolves from its OWN event, before any record exists.
 *
 * The ordering bug this pins: `VERIFIER_BRIEF_COMPLETED` used to carry only
 * `brief_hash`, so the lane could not be answered from the event stream. Its
 * only resolvable source was the stored DecisionRecord, which does not exist
 * until the decision is terminal. Disposition and Consequence resolve from
 * their own events, which land BEFORE that fetch — so the screen showed the
 * outcome first and backfilled the verification that had actually preceded it.
 *
 * Events here are synthesized rather than captured because every capture on
 * disk predates the backend change. `tests/v2/test_pipeline.py` is what pins
 * the real payload; this pins what the projection does with it.
 */
describe('the verifier lane resolves before the terminal record', () => {
  const at = (n: number) => new Date(Date.UTC(2026, 8, 10, 13, 16, n)).toISOString();

  /** The causal event order the backend actually emits. */
  const STREAM: LifecycleEventDTO[] = [
    { event: 'EVIDENCE_SNAPSHOT_CREATED', at: at(18), claim_count: 2 },
    { event: 'INVESTIGATOR_STARTED', at: at(18), model_id: 'us.amazon.nova-pro-v1:0' },
    {
      event: 'APPLICABILITY_BRIEF_COMPLETED',
      at: at(26),
      brief_hash: 'aaaa111122',
      basis: 'SPEC-A7:C',
      required_test_count: 2,
      sufficiency: 'SUFFICIENT',
    },
    { event: 'VERIFIER_STARTED', at: at(26), model_id: 'us.amazon.nova-pro-v1:0' },
    // The payload this change added.
    { event: 'VERIFIER_BRIEF_COMPLETED', at: at(34), brief_hash: 'bbbb333344', sufficiency: 'SUFFICIENT' },
    { event: 'RECONCILIATION_COMPLETED', at: at(34), outcome: 'MATCH', differing_fields: [] },
    { event: 'DISPOSITION_COMPUTED', at: at(34), disposition: 'RELEASE', basis: 'SPEC-A7:C' },
    { event: 'CONSEQUENCE_RECALCULATED', at: at(34), order_id: 'C-417' },
  ] as unknown as LifecycleEventDTO[];

  /** Project the stream truncated after `event`, with NO record — mid-run. */
  const liveAt = (event: string) => {
    const cut = STREAM.slice(0, STREAM.findIndex((e) => e.event === event) + 1);
    return project({
      decisionRecordId: 'DR-live',
      lotId: 'LOT-1001',
      material: 'MAT-ALLOY-7',
      receiptMeta: '',
      events: cut,
      result: null,
      running: true,
    });
  };

  const agentsAt = (event: string) => liveAt(event).spine.find((n) => n.key === 'agents');

  it('resolves the verifier from its own event with no record loaded', () => {
    // The core assertion. Mid-run, nothing terminal has been fetched.
    expect(agentsAt('VERIFIER_BRIEF_COMPLETED')?.verifierLane).toBe('SUFFICIENT');
  });

  it('still shows IN_PROGRESS while the verifier is genuinely running', () => {
    expect(agentsAt('VERIFIER_STARTED')?.verifierLane).toBe('IN_PROGRESS');
  });

  it('leaves the verifier lane unstated before it starts', () => {
    expect(agentsAt('APPLICABILITY_BRIEF_COMPLETED')?.verifierLane ?? null).toBeNull();
    expect(agentsAt('APPLICABILITY_BRIEF_COMPLETED')?.investigatorLane).toBe('SUFFICIENT');
  });

  it('never lets the disposition resolve while the verifier is unresolved', () => {
    // The regression stated directly: at every prefix of the stream, if a
    // disposition is showing then the verifier must ALREADY have resolved.
    // This is what "the outcome cannot visually beat verification" means, and
    // it holds without any client-side stagger because the events are causal.
    for (const e of STREAM) {
      const vm = liveAt(String(e.event));
      const agents = vm.spine.find((n) => n.key === 'agents');
      const disposition = vm.spine.find((n) => n.key === 'disposition');
      const consequence = vm.spine.find((n) => n.key === 'consequence');

      if (disposition?.state === 'terminal') {
        expect(agents?.verifierLane).toBe('SUFFICIENT');
        expect(agents?.state).toBe('completed');
      }
      if (consequence?.state === 'completed') {
        expect(agents?.verifierLane).toBe('SUFFICIENT');
      }
    }
  });

  it('orders the spine investigator -> verifier -> disposition -> consequence', () => {
    // Each stage is still pending at the moment the one before it resolves.
    const atVerifierStart = liveAt('VERIFIER_STARTED');
    expect(atVerifierStart.spine.find((n) => n.key === 'disposition')?.state).toBe('pending');
    expect(atVerifierStart.spine.find((n) => n.key === 'consequence')?.state).toBe('pending');

    const atVerifierDone = liveAt('VERIFIER_BRIEF_COMPLETED');
    expect(atVerifierDone.spine.find((n) => n.key === 'agents')?.state).toBe('completed');
    expect(atVerifierDone.spine.find((n) => n.key === 'disposition')?.state).toBe('pending');

    const atDisposition = liveAt('DISPOSITION_COMPUTED');
    expect(atDisposition.spine.find((n) => n.key === 'disposition')?.state).toBe('terminal');
    expect(atDisposition.spine.find((n) => n.key === 'consequence')?.state).toBe('pending');

    expect(liveAt('CONSEQUENCE_RECALCULATED').spine.find((n) => n.key === 'consequence')?.state)
      .toBe('completed');
  });
});

/**
 * THE CAUSAL INVARIANT.
 *
 * While the Verifier is visibly unresolved, nothing downstream of it may read
 * as finished. A frame showing an unresolved verifier beside a committed
 * RELEASE is causally impossible and reads as a broken product.
 *
 * Polling is what makes it reachable: events arrive in ~900ms batches, so a
 * verifier completing 8s in lands alongside the reconciliation, disposition and
 * consequence that followed it. When the verifier's own event cannot resolve
 * the lane, the canvas would render the whole tail at once.
 */
describe('downstream never resolves past an unresolved verifier', () => {
  const at = (n: number) => new Date(Date.UTC(2026, 8, 10, 13, 16, n)).toISOString();

  const stream = (verifierPayload: Record<string, unknown>): LifecycleEventDTO[] =>
    [
      { event: 'EVIDENCE_SNAPSHOT_CREATED', at: at(18), claim_count: 2 },
      { event: 'INVESTIGATOR_STARTED', at: at(18) },
      {
        event: 'APPLICABILITY_BRIEF_COMPLETED', at: at(26), brief_hash: 'a',
        basis: 'SPEC-A7:C', required_test_count: 2, sufficiency: 'SUFFICIENT',
      },
      { event: 'VERIFIER_STARTED', at: at(26) },
      { event: 'VERIFIER_BRIEF_COMPLETED', at: at(34), ...verifierPayload },
      { event: 'RECONCILIATION_COMPLETED', at: at(34), outcome: 'MATCH', differing_fields: [] },
      { event: 'DISPOSITION_COMPUTED', at: at(34), disposition: 'RELEASE' },
      { event: 'CONSEQUENCE_RECALCULATED', at: at(34), order_id: 'C-417' },
    ] as unknown as LifecycleEventDTO[];

  /** The whole tail delivered at once, as a real poll batch delivers it. */
  const wholeBatch = (events: LifecycleEventDTO[], result: unknown = null) =>
    project({
      decisionRecordId: 'DR-batch', lotId: 'LOT-1001', material: 'MAT-ALLOY-7',
      receiptMeta: '', events, result: result as never, running: true,
    });

  const RESULT = {
    ok: true, decision_record_id: 'DR-batch', disposition: 'RELEASE',
    mutation: { action: 'release_lot', target: 'LOT-1001' },
  };

  // A verifier event carrying no `sufficiency` — a runtime deployed before the
  // payload change, and every decision it already recorded.
  const STALE = { brief_hash: 'b' };
  const CURRENT = { brief_hash: 'b', sufficiency: 'SUFFICIENT' };

  it('holds the whole downstream tail when the verifier cannot resolve', () => {
    const vm = wholeBatch(stream(STALE), RESULT);
    const agents = vm.spine.find((n) => n.key === 'agents');

    // Unresolved verifier...
    expect(agents?.verifierLane ?? null).toBeNull();
    // ...therefore NOTHING downstream may claim to be done.
    expect(agents?.reconciliationSeal).toBe('pending');
    expect(vm.spine.find((n) => n.key === 'disposition')?.state).toBe('pending');
    expect(vm.spine.find((n) => n.key === 'consequence')?.state).toBe('pending');
    expect(vm.outcome.visible).toBe(false);
    expect(vm.dispositionLabel).toBe('');
  });

  it('releases the entire tail as soon as the verifier resolves', () => {
    const vm = wholeBatch(stream(CURRENT), RESULT);
    const agents = vm.spine.find((n) => n.key === 'agents');

    expect(agents?.verifierLane).toBe('SUFFICIENT');
    expect(agents?.reconciliationSeal).toBe('match');
    expect(vm.spine.find((n) => n.key === 'disposition')?.state).toBe('terminal');
    expect(vm.spine.find((n) => n.key === 'consequence')?.state).toBe('completed');
    expect(vm.outcome.visible).toBe(true);
  });

  it('resolves a stale stream once the stored brief arrives', () => {
    // The gate is not a dead end: a historical decision resolves when the
    // record loads, and the whole tail appears with it.
    const vm = project({
      decisionRecordId: 'DR-batch', lotId: 'LOT-1001', material: 'MAT-ALLOY-7',
      receiptMeta: '', events: stream(STALE), result: RESULT as never, running: true,
      record: { verifier: { brief: { sufficiency: 'SUFFICIENT' } } },
    });
    expect(vm.spine.find((n) => n.key === 'agents')?.verifierLane).toBe('SUFFICIENT');
    expect(vm.spine.find((n) => n.key === 'disposition')?.state).toBe('terminal');
    expect(vm.outcome.visible).toBe(true);
  });

  it('never shows a resolved downstream beside an unresolved verifier, at ANY prefix', () => {
    const full = stream(STALE);
    for (let i = 1; i <= full.length; i++) {
      const vm = wholeBatch(full.slice(0, i), RESULT);
      const agents = vm.spine.find((n) => n.key === 'agents');
      // Only meaningful once the verifier is actually in play: before
      // VERIFIER_STARTED the lane is null because the agent does not exist yet,
      // and there is nothing downstream of it to hold.
      const inPlay = full.slice(0, i).some((e) => e.event === 'VERIFIER_STARTED');
      const verifierUnresolved =
        (agents?.verifierLane ?? null) === null || agents?.verifierLane === 'IN_PROGRESS';
      if (!inPlay || !verifierUnresolved) continue;
      expect(agents?.reconciliationSeal).toBe('pending');
      expect(vm.spine.find((n) => n.key === 'disposition')?.state).toBe('pending');
      expect(vm.spine.find((n) => n.key === 'consequence')?.state).toBe('pending');
      expect(vm.outcome.visible).toBe(false);
    }
  });

  it('keeps the activity rail ungated — it is the audit chronology', () => {
    // The canvas withholds presentation; the rail must still show real events
    // as they arrive, or the audit surface would lie by omission.
    const events = stream(STALE);
    const vm = wholeBatch(events, RESULT);
    expect(vm.activity).toHaveLength(events.length);
    expect(vm.activity.map((a) => a.eventType)).toContain('DISPOSITION_COMPUTED');
  });

  it('never withholds a security halt behind a verifier that will never run', () => {
    // A halt is not downstream of verification — it is why there is none.
    const vm = vmOf(hostile, 'LOT-1005');
    expect(vm.outcome.visible).toBe(true);
  });
});
