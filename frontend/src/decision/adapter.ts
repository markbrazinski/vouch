/**
 * Backend DTOs -> DecisionWorkspaceVM.
 *
 * The whole workspace is a projection of one ordered event list plus, once it
 * exists, the terminal authoritative record. That is deliberate: the UI cannot
 * drift from the backend's account of what happened, because there is no second
 * place where "what happened" is decided.
 *
 * Two rules this file exists to enforce:
 *
 *   1. Business state is read from event PAYLOAD FIELDS, never parsed out of
 *      prose. `reason` strings are for humans; a UI that regexes them would
 *      break the moment wording changed, and would be asserting business truth
 *      it did not compute.
 *
 *   2. The active stage moves only on major stage boundaries (D8). Tool traffic
 *      is high-frequency and would make the slot flicker; it belongs in the
 *      Activity rail, which is exactly where the backend already puts it.
 */

import type {
  ActivityEventVM,
  AgentStageVM,
  CompletedStageVM,
  ConsequenceVM,
  DecisionWorkspaceVM,
  DispositionVM,
  EstablishedTruthVM,
  ExtractionProvenanceVM,
  FailureVM,
  OutcomeSummaryVM,
  QualityAuthorityOptionVM,
  IdentityBindingPanelVM,
  QualityAuthorityPanelVM,
  QualityAuthorityRecordVM,
  ReconciliationVM,
  SourceArtifactVM,
  SourceLocatorVM,
  SpineNodeVM,
  StageKey,
} from './model';
import type {
  EvaluateDTO,
  HumanAuthorityDecisionDTO,
  LifecycleEventDTO,
  QualityAuthorityDTO,
  RecoveryCandidateDTO,
  SourceArtifactDTO,
  SourceClaimDTO,
  SourceLocatorDTO,
} from './dto';
import type { SemanticTone } from '../view-models/types';

/** D8. Only these events hand the slot to a new stage. */
const STAGE_OWNER: Record<string, StageKey> = {
  EVIDENCE_RECEIVED: 'evidence',
  INVESTIGATOR_STARTED: 'investigator',
  VERIFIER_STARTED: 'verifier',
  RECONCILIATION_COMPLETED: 'reconciliation',
  DISPOSITION_COMPUTED: 'disposition',
  QUALITY_DECISION_REQUIRED: 'disposition',
  CONSEQUENCE_RECALCULATED: 'consequence',
};

/**
 * D8: the stage that drops the left column and takes the full inner width.
 *
 * Only the CONSEQUENCE. What changed for the factory is the climax, and it
 * earns the whole frame.
 *
 * Reconciliation used to be here too, and that was wrong: it is the moment the
 * governing truth is established, so the document that truth was read from is
 * at its most relevant exactly then.
 *
 * Measured against real runs, that alone does not put the certificate on
 * screen. `get_source` only succeeds once the decision record is queryable
 * (~35s), and the backend writes reconciliation, disposition and consequence in
 * ONE terminal batch — so `active` goes straight to `consequence` and
 * reconciliation is never the active stage for a human-visible window. The
 * source column is therefore reachable on a slow or resumed run, and the header
 * affordance (`View COA`) is what makes the document reachable on every settled
 * decision. Both routes open the same viewer.
 */
const FULL_BLEED: StageKey[] = ['consequence'];

/** Exported so a test can assert the layout rule rather than restate it. */
export const FULL_BLEED_STAGES: readonly StageKey[] = FULL_BLEED;

const STAGE_ORDER: StageKey[] = [
  'evidence',
  'investigator',
  'verifier',
  'reconciliation',
  'disposition',
  'consequence',
];

const ACTOR_BY_EVENT: Record<string, ActivityEventVM['actorType']> = {
  EVIDENCE_RECEIVED: 'evidence',
  EVIDENCE_EXTRACTED: 'evidence',
  EVIDENCE_SNAPSHOT_CREATED: 'evidence',
  EVIDENCE_BINDING_COMPLETED: 'evidence',
  EVIDENCE_BINDING_MISMATCH: 'evidence',
  EVIDENCE_SECURITY_COMPLETED: 'security',
  INVESTIGATOR_STARTED: 'investigator',
  APPLICABILITY_BRIEF_COMPLETED: 'investigator',
  BRIEF_VALIDATION_FAILED: 'investigator',
  VERIFIER_STARTED: 'verifier',
  VERIFIER_BRIEF_COMPLETED: 'verifier',
  RECONCILIATION_COMPLETED: 'system',
  DISPOSITION_COMPUTED: 'system',
  POLICY_EVALUATED: 'system',
  CAPABILITY_ISSUED: 'system',
  MUTATION_COMPLETED: 'system',
  CONSEQUENCE_RECALCULATED: 'operations',
  READINESS_TRANSITIONED: 'operations',
  RECOVERY_EVALUATED: 'operations',
  RECOVERY_EXECUTED: 'operations',
  QUALITY_DECISION_REQUIRED: 'system',
  QUALITY_QUESTION_RAISED: 'system',
  QUALITY_AUTHORITY_RECORDED: 'human',
  EVIDENCE_IDENTITY_ESTABLISHED: 'system',
  HUMAN_EVIDENCE_RECEIVED: 'human',
  DECISION_RESUMED: 'system',
};

const ACTOR_NAME: Record<ActivityEventVM['actorType'], string> = {
  evidence: 'Evidence',
  security: 'Security',
  investigator: 'Applicability Investigator',
  verifier: 'Independent Verifier',
  system: 'Vouch',
  operations: 'Operations',
  human: 'Quality',
};

/** D7: only these three carry optional detail on click. */
const EXPANDABLE = new Set([
  'TOOL_RESULT_BOUND',
  'RECONCILIATION_COMPLETED',
  'DISPOSITION_COMPUTED',
]);

const str = (v: unknown, fallback = ''): string =>
  typeof v === 'string' ? v : typeof v === 'number' ? String(v) : fallback;
const num = (v: unknown): number | undefined =>
  typeof v === 'number' ? v : undefined;
const bool = (v: unknown): boolean => v === true;

export const dispositionTone = (disposition: string): SemanticTone => {
  switch (disposition) {
    case 'RELEASE':
    case 'RELEASED':
      return 'released';
    case 'QUARANTINE':
    case 'QUARANTINED':
      return 'quarantine';
    case 'INSUFFICIENT_EVIDENCE':
      return 'decision';
    default:
      return 'progress';
  }
};

export const clockOf = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(
        d.getSeconds(),
      ).padStart(2, '0')}`;
};

const titleCase = (s: string): string =>
  s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

/**
 * A human label for one event, built from payload FIELDS.
 *
 * Note what this does not do: it never inspects a `reason` string to decide
 * what happened. Every branch reads a typed field the backend computed.
 */
function labelFor(e: LifecycleEventDTO): { short: string; summary?: string } {
  const type = e.event;
  switch (type) {
    case 'EVIDENCE_RECEIVED':
      return { short: 'Evidence received', summary: str(e.content_type) };
    case 'EVIDENCE_SECURITY_COMPLETED': {
      const outcome = str(e.guardrail_outcome, 'NOT_RUN');
      // The detecting control is named, because "security inspection" could
      // describe anything and the authority here is a specific AWS service.
      // Note what is NOT echoed: the payload text itself. The rail is read
      // over someone's shoulder; the artifact viewer is where hostile content
      // is inspected deliberately.
      return outcome === 'DETECTED'
        ? { short: 'Prompt injection detected', summary: 'Amazon Bedrock Guardrails' }
        : { short: 'Security inspection', summary: `Amazon Bedrock Guardrails · ${outcome.toLowerCase()}` };
    }
    case 'EVIDENCE_EXTRACTED': {
      // Sponsor-depth micro-pass: meaning first, method as secondary metadata.
      const claims = num(e.claim_count) ?? 0;
      const structured = bool(e.structured_extraction);
      const gate = (num(e.confidence) ?? 0) >= 0.75;
      if (structured) {
        return {
          short: 'Structured table extracted',
          summary: `${claims} claim${claims === 1 ? '' : 's'} · confidence gate ${gate ? 'passed' : 'not met'}`,
        };
      }
      return { short: 'Evidence extracted', summary: `${claims} claim${claims === 1 ? '' : 's'}` };
    }
    case 'EVIDENCE_BINDING_COMPLETED':
      // This event fires even after a quarantine, carrying the quarantine as
      // its `result`. "Identity bound · BOUND" there read as normal processing
      // continuing past the halt; what actually happened is the document was
      // set aside intact.
      if (str(e.result) === 'QUARANTINED_SECURITY') {
        return { short: 'Evidence quarantined', summary: 'withheld from both agents' };
      }
      if (str(e.binding_status) === 'UNRESOLVED_SUPPLIER_BATCH') {
        // "Identity bound · UNRESOLVED_SUPPLIER_BATCH" would read as a
        // contradiction. What happened is the opposite of a binding: the
        // document named itself and Vouch could not resolve that name.
        return {
          short: 'Identity not established',
          summary: 'supplier batch not linked to this lot',
        };
      }
      return {
        short: 'Identity bound',
        summary: bool(e.bound) ? str(e.binding_status) : str(e.binding_status, 'not bound'),
      };
    case 'EVIDENCE_SNAPSHOT_CREATED':
      return { short: 'Evidence frozen', summary: `${num(e.claim_count) ?? 0} claims` };
    case 'INVESTIGATOR_STARTED':
      return { short: 'Investigator started', summary: str(e.model_id) };
    case 'VERIFIER_STARTED':
      return { short: 'Verifier started', summary: str(e.model_id) };
    case 'TOOL_CALLED':
      return { short: `Tool · ${str(e.tool)}`, summary: str(e.agent) };
    case 'TOOL_RESULT_BOUND':
      return {
        short: `Result bound · ${str(e.tool)}`,
        summary: `${num(e.result_count) ?? 0} record${(num(e.result_count) ?? 0) === 1 ? '' : 's'}`,
      };
    case 'APPLICABILITY_BRIEF_COMPLETED':
      return { short: 'Applicability brief', summary: str(e.sufficiency) };
    case 'VERIFIER_BRIEF_COMPLETED':
      return { short: 'Verifier brief', summary: str(e.sufficiency) };
    case 'BRIEF_VALIDATION_FAILED':
      return { short: 'Brief returned for correction', summary: str(e.agent) };
    case 'RECONCILIATION_COMPLETED':
      return { short: 'Reconciliation', summary: titleCase(str(e.outcome)) };
    case 'DISPOSITION_COMPUTED':
      return { short: 'Disposition computed', summary: str(e.disposition) };
    case 'POLICY_EVALUATED':
      return { short: 'Policy evaluated', summary: str(e.gate_decision) };
    case 'CAPABILITY_ISSUED':
      return { short: 'Capability issued', summary: str(e.action) };
    case 'MUTATION_COMPLETED':
      return { short: 'State change committed', summary: `${str(e.action)} · ${str(e.target)}` };
    case 'CONSEQUENCE_RECALCULATED':
      return { short: 'Consequence recalculated', summary: str(e.order_id) };
    case 'READINESS_TRANSITIONED':
      return { short: 'Readiness changed', summary: `${str(e.from)} → ${str(e.to)}` };
    case 'RECOVERY_EVALUATED':
      return { short: 'Recovery evaluated', summary: `${num(e.candidate_count) ?? 0} candidates` };
    case 'RECOVERY_EXECUTED':
      return { short: 'Recovery executed', summary: str(e.order_id) };
    case 'QUALITY_DECISION_REQUIRED':
      // The backend routes EVERY non-autonomous exit through this one event,
      // including a security quarantine — so the raw label claimed a Quality
      // authority decision on a branch that has none. On an injection the
      // truthful statement is what Vouch did: it stopped.
      return str(e.reason) === 'INJECTION'
        ? { short: 'Decision halted before agent reasoning', summary: 'evidence quarantined' }
        : { short: 'Quality decision required', summary: str(e.reason) };
    case 'QUALITY_QUESTION_RAISED':
      if (str(e.question_type) === 'IDENTITY_BINDING') {
        return {
          short: 'Identity confirmation required',
          summary: [str(e.supplier_batch), str(e.internal_lot_id)]
            .filter(Boolean)
            .join(' · not linked to '),
        };
      }
      return {
        short: 'Applicability question raised',
        summary: [str(e.equivalence_id), str(e.characteristic)].filter(Boolean).join(' · '),
      };
    case 'QUALITY_AUTHORITY_RECORDED': {
      const verb = str(e.decision);
      if (verb === 'CONFIRM_BINDING' || verb === 'KEEP_UNBOUND') {
        return {
          short:
            verb === 'CONFIRM_BINDING'
              ? 'Batch-to-lot mapping confirmed'
              : 'Evidence kept unbound',
          summary: [
            [str(e.supplier_batch), str(e.internal_lot_id)].filter(Boolean).join(' → '),
            str(e.accountable_actor),
          ]
            .filter(Boolean)
            .join(' · '),
        };
      }
      return {
        // The rail row the gate asks for: "QUALITY · Applicability authorized",
        // then "EQV-1 · LOT-1003 · QA-LEAD" underneath it.
        short: verb === 'ESTABLISH_EVIDENCE'
          ? 'Controlling evidence established'
          : 'Kept held',
        summary: [str(e.equivalence_id), str(e.accountable_actor)]
          .filter(Boolean)
          .join(' · '),
      };
    }
    case 'EVIDENCE_IDENTITY_ESTABLISHED':
      return {
        short: 'Identity established',
        summary: [str(e.supplier_batch), str(e.internal_lot_id)]
          .filter(Boolean)
          .join(' → '),
      };
    case 'HUMAN_EVIDENCE_RECEIVED':
      return { short: 'Human evidence received', summary: str(e.authority_source) };
    case 'DECISION_RESUMED':
      return {
        short:
          str(e.trigger) === 'IDENTITY_BINDING'
            ? 'Evidence binding resumed'
            : 'Decision resumed',
        summary: `run ${num(e.run_count) ?? num(e.run_number) ?? 2}`,
      };
    default:
      return { short: titleCase(type) };
  }
}

function statusFor(e: LifecycleEventDTO): ActivityEventVM['resultStatus'] {
  switch (e.event) {
    case 'EVIDENCE_SECURITY_COMPLETED':
      return str(e.guardrail_outcome) === 'DETECTED' ? 'bad' : 'good';
    case 'RECONCILIATION_COMPLETED':
      return str(e.outcome) === 'MATERIAL_DISAGREEMENT' ? 'caution' : 'good';
    case 'DISPOSITION_COMPUTED':
      return str(e.disposition) === 'RELEASE' ? 'good' : 'caution';
    case 'QUALITY_DECISION_REQUIRED':
      // An injection halt is a security event, not an open question routed to
      // a human, and the rail colours it accordingly.
      return str(e.reason) === 'INJECTION' ? 'bad' : 'caution';
    case 'QUALITY_QUESTION_RAISED':
    case 'BRIEF_VALIDATION_FAILED':
      return 'caution';
    case 'QUALITY_AUTHORITY_RECORDED':
      return ['ESTABLISH_EVIDENCE', 'CONFIRM_BINDING'].includes(str(e.decision))
        ? 'good'
        : 'caution';
    case 'EVIDENCE_IDENTITY_ESTABLISHED':
      return 'good';
    case 'MUTATION_COMPLETED':
    case 'RECOVERY_EXECUTED':
      return 'good';
    default:
      return 'neutral';
  }
}

/**
 * Which run each event belongs to, derived.
 *
 * The backend does not put `run_number` on the wire: `rerun()` increments
 * `run_count` on the RECORD, and the only in-stream markers of that boundary
 * are HUMAN_EVIDENCE_RECEIVED and DECISION_RESUMED. Without this, every event
 * of a resumed decision reported run 1 and Hero B's second run was
 * indistinguishable from its first.
 *
 * The boundary opens at the HUMAN act rather than at DECISION_RESUMED: the
 * human is what causes the new run, and the evidence-intake events carrying it
 * would otherwise be filed under the run they ended. Both markers are counted
 * so a stream carrying only one still steps exactly once.
 *
 * One function, because the activity rail and the agent stage cards must not
 * disagree about which run the operator is looking at.
 */
export function runNumbers(events: LifecycleEventDTO[]): number[] {
  let derived = 1;
  let stepped = false;
  return events.map((e) => {
    // The human act that opens a run, whichever form it took: supplying
    // evidence, or establishing an identity. A confirmation filed under run 1
    // reads as something the first run did, when it is precisely the thing
    // that ended it.
    const humanAct =
      e.event === 'HUMAN_EVIDENCE_RECEIVED' ||
      (e.event === 'QUALITY_AUTHORITY_RECORDED' &&
        str(e.decision) === 'CONFIRM_BINDING');
    if (humanAct) {
      derived += 1;
      stepped = true;
    } else if (e.event === 'DECISION_RESUMED') {
      if (!stepped) derived += 1;
      stepped = false;
    }
    return derived;
  });
}

export function toActivity(events: LifecycleEventDTO[]): ActivityEventVM[] {
  // A `run_number` IS still honoured if it ever appears: this is a fallback,
  // never an override.
  const runOf = runNumbers(events);

  return events.map((e, index) => {
    // The binding stage is normally an Evidence act, but the row it renders on
    // a quarantined artifact states what VOUCH did with the document, so the
    // attribution follows the sentence.
    const actorType: ActivityEventVM['actorType'] =
      e.event === 'EVIDENCE_BINDING_COMPLETED' && str(e.result) === 'QUARANTINED_SECURITY'
        ? 'system'
        : (ACTOR_BY_EVENT[e.event] ?? 'system');
    const { short, summary } = labelFor(e);
    const sequence = num(e.sequence) ?? index + 1;
    const detail: { label: string; value: string }[] = [];

    if (e.event === 'TOOL_RESULT_BOUND') {
      if (e.tool) detail.push({ label: 'Tool', value: str(e.tool) });
      if (e.result_count !== undefined)
        detail.push({ label: 'Records', value: String(e.result_count) });
      if (e.elapsed_ms !== undefined)
        detail.push({ label: 'Elapsed', value: `${e.elapsed_ms} ms` });
    } else if (e.event === 'RECONCILIATION_COMPLETED') {
      detail.push({ label: 'Outcome', value: titleCase(str(e.outcome)) });
      const differing = Array.isArray(e.differing_fields) ? (e.differing_fields as string[]) : [];
      if (differing.length) detail.push({ label: 'Differing', value: differing.join(', ') });
    } else if (e.event === 'DISPOSITION_COMPUTED') {
      detail.push({ label: 'Disposition', value: str(e.disposition) });
      if (e.basis) detail.push({ label: 'Basis', value: str(e.basis) });
    }

    return {
      eventId: str(e.event_id, `${e.decision_record_id}:${sequence}`),
      sequence,
      timestamp: str(e.at),
      clock: clockOf(str(e.at)),
      eventType: e.event,
      actorType,
      actorDisplayName: ACTOR_NAME[actorType],
      toolId: e.tool ? str(e.tool) : undefined,
      shortLabel: short,
      resultSummary: summary,
      resultStatus: statusFor(e),
      runNumber: num(e.run_number) ?? runOf[index],
      expandable: EXPANDABLE.has(e.event) && detail.length > 0,
      detail: detail.length ? detail : undefined,
    };
  });
}

/** "2026-08-15T08:00" -> "08:00". The date is the same day throughout. */
export const slotTime = (slot: string): string => {
  const t = slot.split('T')[1];
  return t ? t.slice(0, 5) : slot;
};

/**
 * A sentence for one recovery candidate, composed from the backend's own
 * reason code and computed facts. Never parsed out of prose, and never
 * arithmetic performed here.
 */
export function recoveryDetail(c: RecoveryCandidateDTO): string {
  const f = (c.facts ?? {}) as Record<string, unknown>;
  switch (c.reason_code) {
    case 'INSUFFICIENT_QUANTITY':
      return `Short by ${f.short_by} of ${c.candidate_id} — ${f.available} available against ${f.required} required.`;
    case 'NOT_APPROVED':
      return `${f.available} in stock, but ${c.candidate_id} is not an approved substitution for ${f.product}. Stock is not authority.`;
    case 'FEASIBLE':
      return `Materials ready on ${f.resource}; the ${slotTime(String(f.target_slot ?? ''))} slot is free.`;
    case 'SLOT_OCCUPIED':
      return `The target slot is already committed.`;
    case 'MATERIALS_NOT_READY':
      return `Required material for this order is not released.`;
    case 'RESOURCE_MISMATCH':
      return `Runs on a different resource; it cannot take this slot.`;
    default:
      return c.reason_code ? titleCase(String(c.reason_code)) : '';
  }
}

/** One failing comparison, exactly as the disposition engine computed it. */
export interface DispositionFailure {
  characteristic?: string;
  value?: number;
  units?: string;
  min_value?: number | null;
  max_value?: number | null;
  threshold_text?: string;
}

/**
 * The deterministic disposition reason, said the way a person says it.
 *
 * Built from the `failures` PAYLOAD FIELD on DISPOSITION_COMPUTED — the same
 * comparison the engine made, as data. Per rule 1 at the top of this file, the
 * prose `reason` is never parsed: regexing it would make the backend's wording
 * load-bearing and have the UI assert business truth it did not compute.
 *
 * Only FAILING requirements appear. A passing one is not why the lot was
 * quarantined, and listing it dilutes the answer to "why".
 *
 * Returns null when the engine emitted no structured failures — an older
 * record, or a disposition that did not fail on a value — and the caller falls
 * back to the reason string the backend did provide.
 */
export function failureProse(
  failures: DispositionFailure[] | undefined,
  basis?: string,
): string | null {
  if (!failures?.length) return null;

  // "SPEC-A7:C" -> "SPEC-A7 Rev C". Short form, because this now sits INSIDE
  // the requirement clause rather than in a sentence of its own — the reader
  // needs the governing basis attached to the number it governs, not
  // announced separately and then repeated.
  const spec = basis ? `${basis.replace(':', ' Rev ')} requires` : 'Requirement:';

  const sentences = failures.map((f) => {
    const name = str(f.characteristic).replace(/_/g, ' ').toLowerCase();
    const units = f.units ? ` ${f.units}` : '';
    // A one-sided minimum reads as "at least X"; anything else keeps the
    // engine's own threshold wording rather than inventing a comparator.
    const limit =
      typeof f.min_value === 'number' && (f.max_value === null || f.max_value === undefined)
        ? `at least ${f.min_value}${units}`
        : str(f.threshold_text);
    return `${name} was ${f.value}${units}; ${spec} ${limit}`;
  });

  // One sentence, and it leads with WHY this was not a judgement call. The
  // deterministic engine failed a rule — that is the whole answer to "why",
  // and the revision story is secondary context rendered elsewhere.
  return `Deterministic rule failed — ${sentences.join('. ')}.`;
}

const localeNum = (v: unknown): string =>
  typeof v === 'number' ? String(v) : str(v);

function locatorLabel(l: SourceLocatorDTO): string {
  const parts: string[] = [];
  if (l.page !== undefined) parts.push(`Page ${l.page}`);
  if (l.table !== undefined) parts.push(`Table ${l.table}`);
  if (l.row_label) parts.push(titleCase(l.row_label));
  if (l.column_label) parts.push(titleCase(l.column_label));
  return parts.join(' · ');
}

/** Sponsor depth. Returns null for every ordinary document. */
function extractionOf(a: SourceArtifactDTO): ExtractionProvenanceVM | null {
  const structured = bool(a.structured_extraction);
  const method = str(a.extraction_method);
  if (!structured && !method) return null;

  const claimCount = a.claims?.length ?? a.source_locators?.length ?? 0;
  return {
    method,
    // Meaning first. The method is metadata, never the headline.
    headline: structured ? 'Structured table extracted' : 'Text extracted',
    structured,
    confidence: a.extraction_confidence,
    confidenceGatePassed: a.confidence_gate_passed,
    identityTrusted: a.identity_trusted,
    reason: a.structured_reason,
    claimCount,
  };
}

/**
 * The canonical claims the decision actually froze, keyed by artifact.
 *
 * `get_source` reports a claim COUNT but never the claims themselves. The
 * claims do exist on an authoritative surface: the stored decision record
 * carries `evidence.canonical_claims`, and `get_decision` returns that document
 * whole. Each claim names the artifact it came from (`evidence_artifact_id`),
 * so this is a join over truth the backend already publishes — not a new
 * contract, and not a value invented here.
 *
 * Every claim arrives with its own provenance: characteristic, value, units,
 * method, condition and `source_locator`. That is what lets the viewer itemize
 * WHAT was read and WHERE it was read from, instead of admitting a bare count.
 */
export function claimsByArtifact(
  record: Record<string, unknown> | null | undefined,
): Map<string, SourceClaimDTO[]> {
  const out = new Map<string, SourceClaimDTO[]>();
  if (!record) return out;
  const evidence = record.evidence as Record<string, unknown> | undefined;
  const claims = evidence?.canonical_claims;
  if (!Array.isArray(claims)) return out;
  for (const raw of claims as SourceClaimDTO[]) {
    if (!raw || typeof raw !== 'object') continue;
    const artifactId = str(raw.evidence_artifact_id);
    if (!artifactId) continue;
    const list = out.get(artifactId);
    if (list) list.push(raw);
    else out.set(artifactId, [raw]);
  }
  return out;
}

export function toSource(a: SourceArtifactDTO, joined?: SourceClaimDTO[]): SourceArtifactVM {
  // Field names verified against a LIVE get_source response. Three of them
  // differ from what the DTO shape suggested — `trust_class` not `trust_label`,
  // `excluded_from_decision_use` not `excluded_from_decision`, and
  // `security_state` arriving UPPERCASE — so both spellings are accepted rather
  // than one being guessed at.
  const trustRaw = str(a.trust_class) || str(a.trust_label, 'UNTRUSTED_SUPPLIER');
  const securityRaw = str(a.security_state, 'CLEARED').toUpperCase();
  const status = str(a.status);
  const quarantined =
    securityRaw === 'QUARANTINED' ||
    status === 'QUARANTINED_SECURITY' ||
    bool(a.prompt_attack_detected);

  const trustClass: SourceArtifactVM['trustClass'] = quarantined
    ? 'quarantined'
    : trustRaw === 'HUMAN_AUTHORIZED'
      ? 'human_authorized'
      : trustRaw === 'AUTHORITATIVE_INTERNAL'
        ? 'internal'
        : 'supplier_untrusted';

  const locators: SourceLocatorVM[] = (a.source_locators ?? []).map((l) => ({
    label: locatorLabel(l),
    page: l.page,
    table: l.table,
    rowLabel: l.row_label,
    columnLabel: l.column_label,
    cell: l.cell,
    confidence: l.confidence,
    structured: true,
  }));

  // The artifact's own claims when a surface ever carries them, otherwise the
  // ones joined from the durable record. Never both — one claim, one row.
  const claimSource = a.claims?.length ? a.claims : (joined ?? []);
  const claims: SourceClaimVMLocal[] = claimSource.map((c) => ({
    label: titleCase(str(c.characteristic)),
    value: [localeNum(c.value), str(c.units)].filter(Boolean).join(' '),
    locator: str(c.source_locator),
    method: str(c.method),
    condition: str(c.condition),
    trustClass: str(c.trust_label, trustRaw),
  }));

  const hash = str(a.content_hash);
  const pageCount = num(a.page_count);

  return {
    artifactId: str(a.artifact_id),
    displayName:
      str(a.display_name) || str(a.document_identity) || str(a.document_type) || str(a.artifact_id),
    documentType: str(a.document_identity) || str(a.document_type, 'document'),
    trustClass,
    trustLabel: trustRaw,
    securityState: quarantined ? 'quarantined' : securityRaw === 'CLEARED' ? 'cleared' : 'pending',
    versionId: str(a.version_id) || str(a.object_version),
    hashSummary: hash ? `${hash.slice(0, 12)}…` : '',
    pageCount,
    excludedFromDecision:
      bool(a.excluded_from_decision_use) || bool(a.excluded_from_decision) || quarantined,
    claims,
    // The backend reports the count even when it does not itemize the claims.
    claimCount: num(a.claim_count) ?? claims.length,
    locators,
    extraction: extractionOf(a),
    // `view_ref` presence only. The URL itself is never carried on the model:
    // it is a 300s bearer credential and is fetched at open time.
    openable: Boolean(a.view_ref || a.view_url),
  };
}

interface SourceClaimVMLocal {
  label: string;
  value: string;
  locator: string;
  method: string;
  condition: string;
  trustClass: string;
}

/** Latest event of a type, or undefined. Events arrive in ascending sequence. */
const last = (events: LifecycleEventDTO[], type: string): LifecycleEventDTO | undefined => {
  for (let i = events.length - 1; i >= 0; i -= 1) if (events[i].event === type) return events[i];
  return undefined;
};

const allOf = (events: LifecycleEventDTO[], type: string): LifecycleEventDTO[] =>
  events.filter((e) => e.event === type);

/**
 * An escalation that is still OUTSTANDING — not one a later run already answered.
 *
 * `QUALITY_DECISION_REQUIRED` is durable: it stays in the stream forever once
 * emitted. On a resumed decision the human answers the question, the agents
 * re-run, and a real DISPOSITION_COMPUTED plus a real mutation follow it — but
 * `last(events, 'QUALITY_DECISION_REQUIRED')` still returns run 1's escalation,
 * so the header claimed "QUALITY DECISION" on a lot that had already RELEASED.
 *
 * The live `evaluate` response hid this: it carries only the CURRENT run's
 * events, so run 1's escalation is absent and the terminal frame looked right.
 * `get_events` returns the whole history, which is what Records, Today and any
 * saved-run playback read — and there the answered question came back to life.
 *
 * Caught on the LOT-1003 and LOT-1004 golden captures, where the escalation at
 * sequence 30 and 6 is superseded by a disposition at 66 and 28.
 *
 * A question the final run genuinely ended on is still returned: nothing
 * supersedes it, so there is nothing to compare against.
 */
const openQualityDecision = (
  events: LifecycleEventDTO[],
): LifecycleEventDTO | undefined => {
  const qdr = last(events, 'QUALITY_DECISION_REQUIRED');
  if (!qdr) return undefined;
  const at = events.indexOf(qdr);
  // Only a COMMITTED state change supersedes it. A later DISPOSITION_COMPUTED
  // alone does not: on the abstain path the disposition is computed and then
  // REFUSED by the gate, which is the very sequence that raises the question —
  // treating it as settlement would hide every genuine abstention.
  //
  // A later DECISION_RESUMED does not settle it either: a resumed run may
  // abstain a second time, and it is the last escalation that is outstanding.
  // Only a mutation proves the case actually reached an authorized outcome.
  const settled = events.slice(at + 1).some((e) => e.event === 'MUTATION_COMPLETED');
  return settled ? undefined : qdr;
};

/**
 * D8. The active stage is derived from the last STAGE BOUNDARY event only.
 * `TOOL_CALLED` is intentionally absent from STAGE_OWNER.
 */
export function activeStageFrom(events: LifecycleEventDTO[]): StageKey | null {
  let owner: StageKey | null = null;
  for (const e of events) {
    const next = STAGE_OWNER[e.event];
    if (next) owner = next;
  }
  return owner;
}

function agentFrom(
  events: LifecycleEventDTO[],
  role: 'investigator' | 'verifier',
): AgentStageVM | null {
  const startedType = role === 'investigator' ? 'INVESTIGATOR_STARTED' : 'VERIFIER_STARTED';
  const doneType =
    role === 'investigator' ? 'APPLICABILITY_BRIEF_COMPLETED' : 'VERIFIER_BRIEF_COMPLETED';

  const started = last(events, startedType);
  if (!started) return null;
  const done = last(events, doneType);

  // Tool results are attributed by the `agent` field the backend stamps, so the
  // two agents' consulted-records lists cannot bleed into each other.
  const records = allOf(events, 'TOOL_RESULT_BOUND')
    .filter((e) => str(e.agent) === role)
    .map((e) => ({
      mark: '·',
      label: titleCase(str(e.tool)),
      value: `${num(e.result_count) ?? 0} record${(num(e.result_count) ?? 0) === 1 ? '' : 's'}`,
      emphasis: false,
    }));

  const sufficiency = done ? str(done.sufficiency) : '';
  const sufficient = sufficiency === 'SUFFICIENT';

  return {
    role,
    // Same derived boundary the rail uses, so the "RUN 2" badge and the rail
    // cannot contradict each other on a resumed decision.
    runNumber: num(started.run_number) ?? runNumbers(events)[events.indexOf(started)] ?? 1,
    state: done ? 'complete' : 'active',
    modelId: str(started.model_id),
    recordsConsulted: records,
    // Sufficiency is a COVERAGE question, never a conformance one: SUFFICIENT
    // means every required test has applicable evidence, INCLUDING when a
    // measured value falls outside its limit. "Evidence is applicable" was read
    // as "the lot is fine" on a lot that was about to be quarantined, so the
    // copy now names coverage explicitly and leaves the verdict to the
    // disposition, which is where it is actually decided.
    // The empty-sufficiency branch is for a Verifier event that states no
    // sufficiency. Live runs no longer produce one — both roles publish it —
    // but decisions recorded earlier do, and they replay through here. Treating
    // that silence as "not sufficient" printed a flat contradiction: its own
    // lane read "Evidence covers the requirement" while this line said the
    // opposite, on a lot that released. Unknown is stated as unknown.
    //
    // `basis` remains investigator-only: the verifier is deliberately blind, so
    // resultBody still reports it as unresolved for that role.
    resultTitle: done
      ? sufficiency === ''
        ? 'Independent reconstruction complete'
        : sufficient
          ? 'Every required test has applicable evidence'
          : 'Some required tests have no applicable evidence'
      : 'Working',
    resultBody: done
      ? `Governing basis ${str(done.basis, 'unresolved')} · ${num(done.required_test_count) ?? 0} required test(s)`
      : 'Consulting authoritative records.',
    resultTone: done ? (sufficiency === '' ? 'progress' : sufficient ? 'released' : 'decision') : 'progress',
    isIndependent: role === 'verifier',
    basis: done ? str(done.basis) : undefined,
    sufficiency: sufficiency || undefined,
  };
}

function reconciliationFrom(events: LifecycleEventDTO[]): ReconciliationVM | null {
  const e = last(events, 'RECONCILIATION_COMPLETED');
  if (!e) return null;
  const outcome = str(e.outcome, 'MATCH') as ReconciliationVM['state'];
  const differing = Array.isArray(e.differing_fields) ? (e.differing_fields as string[]) : [];

  const investigator = last(events, 'APPLICABILITY_BRIEF_COMPLETED');
  const verifier = last(events, 'VERIFIER_BRIEF_COMPLETED');

  // Only material dimensions, per D4.
  //
  // Live payloads settled a design question here: VERIFIER_BRIEF_COMPLETED
  // carries no `basis`. That is the verifier-blind architecture showing through
  // the event surface, and it means a side-by-side value table would have to
  // source the Verifier's basis column from somewhere it does not exist. Rather
  // than fabricate one or borrow the Investigator's, the comparison is shown as
  // what the backend actually computed: the reconciliation OUTCOME plus the
  // fields it found differing.
  //
  // The event does now carry the verifier's own `sufficiency`, but this table
  // deliberately still reports agrees/differs from `differing_fields` rather
  // than printing the two values: the RECONCILIATION is the authority on
  // whether they differ materially, and two equal strings would assert an
  // agreement this projection did not compute.
  const dimensions: ReconciliationVM['dimensions'] = [];
  const iBasis = str(investigator?.basis);
  if (iBasis) {
    dimensions.push({
      dimension: 'Governing basis',
      investigatorValue: iBasis,
      verifierValue: differing.includes('governing_basis') ? 'differs' : 'agrees',
      agrees: !differing.includes('governing_basis'),
    });
  }
  const iSuff = str(investigator?.sufficiency);
  if (iSuff) {
    dimensions.push({
      dimension: 'Sufficiency',
      investigatorValue: iSuff,
      verifierValue: differing.includes('sufficiency') ? 'differs' : 'agrees',
      agrees: !differing.includes('sufficiency'),
    });
  }
  if (verifier) {
    dimensions.push({
      dimension: 'Brief hash',
      investigatorValue: str(investigator?.brief_hash).slice(0, 10) || '—',
      verifierValue: str(verifier.brief_hash).slice(0, 10) || '—',
      agrees: true,
    });
  }

  const note =
    outcome === 'MATERIAL_DISAGREEMENT'
      ? `The two independent reads differ on ${differing.join(', ') || 'a material dimension'}. Vouch does not proceed on a disagreement.`
      : outcome === 'NON_MATERIAL_DIFFERENCE'
        ? 'The reads differ only where the difference cannot change the outcome.'
        : 'Both independent reads agree on every material dimension.';

  return { state: outcome, dimensions, note };
}

/**
 * True once the scanner has quarantined the evidence.
 *
 * One definition, because three surfaces need the same answer and a security
 * halt that only two of them agreed on is how a placeholder gets rendered.
 */
function securityHalted(events: LifecycleEventDTO[]): boolean {
  const security = last(events, 'EVIDENCE_SECURITY_COMPLETED');
  return security ? str(security.result) === 'QUARANTINED_SECURITY' : false;
}

function dispositionFrom(
  events: LifecycleEventDTO[],
  result: EvaluateDTO | null,
): DispositionVM | null {
  const computed = last(events, 'DISPOSITION_COMPUTED');
  const qdr = openQualityDecision(events);
  if (!computed && !qdr) return null;
  // Integration contract invariant 6. On a security quarantine the SAME
  // QUALITY_DECISION_REQUIRED event is emitted by the scanner, before any
  // adjudication exists — so keying off it alone renders a disposition panel
  // whose every field is empty ("Governing basis —, Failing 0, Missing 0").
  // That is the placeholder the invariant forbids: security halts the spine,
  // it does not produce a weak verdict.
  if (!computed && securityHalted(events)) return null;

  const disposition = str(computed?.disposition) || result?.disposition || '';
  const mutations = allOf(events, 'MUTATION_COMPLETED').map(
    (e) => `${titleCase(str(e.action))} · ${str(e.target)} · v${num(e.before_version) ?? '?'} → v${num(e.after_version) ?? '?'}`,
  );
  const policies = allOf(events, 'POLICY_EVALUATED').map(
    (e) => `Policy ${str(e.gate_decision)} · ${str(e.policy_version)}`,
  );
  const capabilities = allOf(events, 'CAPABILITY_ISSUED').map(
    (e) => `Capability issued · ${str(e.action)} · expires ${str(e.expiry)}`,
  );

  // On an abstention the DISPOSITION_COMPUTED event carries no basis, but the
  // Investigator did resolve one and the context column already shows it.
  // Falling back keeps the two panels from contradicting each other.
  const basis = str(computed?.basis) || str(last(events, 'APPLICABILITY_BRIEF_COMPLETED')?.basis);
  const differences = Array.isArray(qdr?.material_differences)
    ? (qdr!.material_differences as string[])
    : [];

  return {
    disposition,
    tone: dispositionTone(disposition),
    governingBasis: basis,
    requirementValue: str(computed?.requirement_value),
    boundValue: str(computed?.bound_value),
    basisChain: [
      { label: 'Governing basis', value: basis || '—' },
      {
        label: 'Failing requirements',
        value: String(num(computed?.failing_test_count) ?? 0),
        tone: (num(computed?.failing_test_count) ?? 0) > 0 ? 'quarantine' : 'released',
      },
      {
        label: 'Missing requirements',
        value: String(num(computed?.missing_test_count) ?? 0),
        tone: (num(computed?.missing_test_count) ?? 0) > 0 ? 'decision' : 'released',
      },
    ],
    stateMutation: [...policies, ...capabilities, ...mutations],
    qualityDecisionRequired: Boolean(qdr) || Boolean(result?.quality_decision_required),
    qdrQuestion: qdr ? str(qdr.reason) : undefined,
    materialDifferences: differences,
  };
}

/**
 * The authoritative consequence, wherever this response happens to carry it.
 *
 * A LIVE evaluate response carries `consequences` at the top level. A STORED
 * decision read back through `get_decision` carries the same object one level
 * down, on `record` — and `settle()` hands the whole response through as
 * `result`. Reading only the top level meant a settled decision rendered its
 * readiness change and its executed resequence (both reconstructible from
 * events) while the four recovery CANDIDATES silently vanished — the refused
 * substitute among them, which is the part that shows Vouch weighed options
 * and rejected them before moving the plan.
 */
function consequencesOf(result: EvaluateDTO | null): EvaluateDTO['consequences'] {
  if (result?.consequences) return result.consequences;
  const record = (result as Record<string, unknown> | null)?.record as
    | Record<string, unknown>
    | undefined;
  return (record?.consequences as EvaluateDTO['consequences']) ?? undefined;
}

function consequenceFrom(
  events: LifecycleEventDTO[],
  result: EvaluateDTO | null,
): ConsequenceVM | null {
  const recalcs = allOf(events, 'CONSEQUENCE_RECALCULATED');
  const evaluated = last(events, 'RECOVERY_EVALUATED');
  const executed = last(events, 'RECOVERY_EXECUTED');
  const transitions = allOf(events, 'READINESS_TRANSITIONED');
  if (!recalcs.length && !evaluated && !executed && !transitions.length) return null;

  // Same staleness as `readinessChanges` below: the recalculation ran before
  // recovery, so the resequenced order's row no longer describes it. Dropping
  // it here also keeps NEXT ACTION honest — an order that was successfully
  // moved is not an open gap for the operator to close.
  const recovered = str(executed?.order_id);
  const consequences = consequencesOf(result);

  // One row per ORDER, not one per emitted event.
  //
  // A resumed or retried decision runs the consequence pass again, so a real
  // record carries two CONSEQUENCE_RECALCULATED events for the same order —
  // the live LOT-1002 record has 96 events across two passes. Rendering both
  // duplicated the C-417 card and made NEXT ACTION repeat its own sentence.
  // The LAST recalculation for an order is the current one; earlier passes are
  // superseded history, not additional orders.
  const latestPerOrder = [
    ...new Map(recalcs.map((e) => [str(e.order_id), e])).values(),
  ];

  const metrics: ConsequenceVM['metrics'] = latestPerOrder
    .filter((e) => !(recovered && str(e.order_id) === recovered))
    .map((e) => {
    // `coverage_delta` is the LOT's inventory delta — the same figure for every
    // order in the batch — so it rendered as "coverage 0" beside an order that
    // was fully covered. The order's own composition is what belongs here.
    const required = num(e.required);
    const available = num(e.available);
    const planned = num(e.planned) ?? 0;
    const uncovered = num(e.uncovered) ?? 0;
    const note =
      required === undefined || available === undefined
        ? undefined
        : uncovered > 0
          ? `${available} of ${required} released · short ${uncovered}`
          : planned > 0
            ? `${available} of ${required} released · ${planned} queued`
            : `${available} of ${required} released`;
    return {
    label: str(e.order_id),
    value: str(e.order_readiness),
    note,
    materialId: str(e.material_id) || undefined,
    uncovered,
    severity:
      str(e.order_readiness) === 'BLOCKED'
        ? 'blocked'
        : str(e.order_readiness) === 'AT_RISK'
          ? 'atrisk'
          : 'released',
    };
  });

  // The order recovery actually moved. Its readiness was computed BEFORE
  // recovery ran, so a transition recorded for it is superseded by the
  // resequence that followed in the same decision — rendering both showed
  // "C-418 READY → BLOCKED" beside a card announcing C-418 as the executed
  // recovery. Only the later fact is still true, so the stale card is dropped
  // rather than left to contradict it.
  const readinessChanges = (
    consequences?.readiness_changes ??
    // Same de-duplication as `metrics`: a retried pass re-emits the transition
    // for an order it already reported.
    [
      ...new Map(
        transitions.map((e) => [
          str(e.order_id),
          { order_id: str(e.order_id), from: str(e.from), to: str(e.to) },
        ]),
      ).values(),
    ]
  )
    .filter((c) => !(recovered && c.order_id === recovered))
    .map((c) => ({ orderId: c.order_id, from: c.from, to: c.to }));

  // WHICH candidate the engine chose, from the engine's own `selected` — not
  // inferred from ELIGIBLE. Several candidates can be eligible; only the
  // selected one moved the factory.
  const selectedId = str(consequences?.recovery?.selected?.candidate_id);

  const candidates = (consequences?.recovery?.candidates ?? []).map((c) => ({
    selected: Boolean(selectedId) && c.candidate_id === selectedId,
    candidateId: c.candidate_id,
    kind: str(c.kind, 'candidate'),
    title: c.candidate_id,
    // The backend states WHY as a code plus computed facts, never as prose.
    // Composing the sentence here keeps the arithmetic where it belongs — in
    // Python — while still reading like something a person wrote.
    detail: recoveryDetail(c),
    verdict: c.verdict,
    tone: (c.verdict === 'ELIGIBLE'
      ? 'released'
      : c.verdict === 'REFUSED'
        ? 'refused'
        : 'progress') as SemanticTone,
  }));

  return {
    metrics,
    readinessChanges,
    candidates,
    // Open by default; `project()` defers it at the terminal frame, which is
    // the only place it competes with anything.
    deferCandidates: false,
    executed: executed
      ? {
          tag: str(executed.order_id),
          line: (() => {
            const from = str(executed.from_slot);
            const to = str(executed.to_slot) || str(executed.target_slot);
            const blocked = str(executed.blocked_order_id);
            if (from && to) return `moved ${slotTime(from)} → ${slotTime(to)}${blocked ? `, into the slot ${blocked} vacated` : ''}`;
            return 'resequenced into a vacated slot';
          })(),
          caveat: str(executed.caveat) || undefined,
        }
      : null,
  };
}

function outcomeFrom(
  events: LifecycleEventDTO[],
  result: EvaluateDTO | null,
  failure: FailureVM | null,
): OutcomeSummaryVM {
  // A technical failure never produces an outcome with a disposition in it.
  if (failure?.kind === 'TECHNICAL_FAILURE') {
    return {
      visible: true,
      kind: 'technical_failure',
      headline: failure.headline,
      tone: 'progress',
      lines: [failure.detail],
    };
  }

  const security = last(events, 'EVIDENCE_SECURITY_COMPLETED');
  if (security && str(security.result) === 'QUARANTINED_SECURITY') {
    // The detection is Amazon Bedrock Guardrails' Prompt Attack filter, not an
    // agent result. Naming the Investigator, the Verifier or the model here
    // would credit reasoning that provably never ran — the whole point of this
    // path is that the document was stopped BEFORE either agent started.
    return {
      visible: true,
      kind: 'evidence_quarantined',
      headline: 'Prompt injection detected',
      tone: 'quarantine',
      lines: [
        'Amazon Bedrock Guardrails quarantined this supplier evidence before it reached either decision agent.',
        'No disposition was made. No production state changed.',
      ],
      chip: { label: 'SECURITY QUARANTINE', tone: 'quarantine' },
    };
  }

  const qdr = openQualityDecision(events);
  // A question that has been ANSWERED is no longer open. On a resumed case the
  // rail deliberately keeps run 1's escalation, so reading it alone left a
  // released lot still reporting "Quality decision required" — the outcome
  // panel contradicting the disposition directly beneath it.
  //
  // Ordering decides it: an authority recorded AFTER the escalation settled
  // that escalation. Comparing sequence rather than presence is what keeps a
  // second, later disagreement legible.
  // Position in the already-sorted array, not the `sequence` field. Not every
  // transport populates `sequence` — the runtime's own evaluate/authority
  // responses do not — and `(0) > (0)` is false, so an answered question went
  // on reporting itself as open and a released lot still showed "Quality
  // decision required" above its own RELEASE.
  const indexOfLast = (type: string): number => {
    for (let i = events.length - 1; i >= 0; i -= 1) if (events[i].event === type) return i;
    return -1;
  };
  const settledAt = indexOfLast('QUALITY_AUTHORITY_RECORDED');
  const answered = settledAt > -1 && settledAt > indexOfLast('QUALITY_DECISION_REQUIRED');
  if (!answered && (qdr || result?.quality_decision_required)) {
    return {
      visible: true,
      kind: 'quality_decision_required',
      headline: 'Quality decision required',
      tone: 'decision',
      // `reason` on this event is a CODE ("DISAGREEMENT", "INSUFFICIENT"),
      // which is fine for a log and unreadable in an outcome panel. Each code
      // gets its sentence; anything unrecognised falls back to the engine's
      // own prose rather than a code rendered as English.
      lines: [
        str(qdr?.reason) === 'DISAGREEMENT'
          ? 'Independent review selected different controlling evidence. ' +
            'No disposition was made.'
          : str(qdr?.reason) === 'INSUFFICIENT'
            ? 'The evidence does not establish an answer, so nothing was decided.'
            : result?.reason || 'The evidence could not establish an answer.',
      ],
      chip: { label: 'AWAITING QUALITY', tone: 'decision' },
    };
  }

  const computed = last(events, 'DISPOSITION_COMPUTED');
  const disposition = str(computed?.disposition) || result?.disposition || '';
  if (!disposition) return { visible: false, kind: 'released', headline: '', tone: 'progress', lines: [] };

  const consequence = consequenceFrom(events, result);
  const blocked = consequence?.readinessChanges.filter((c) => c.to === 'BLOCKED') ?? [];

  if (disposition === 'RELEASE') {
    // Where a human established the controlling evidence, the outcome says so.
    // "Every governing requirement was met" is true but omits the fact an
    // operator most needs to see on this record: the release rests on a
    // measurement Quality chose, and the choice is part of the answer.
    const established = str(
      last(events, 'QUALITY_AUTHORITY_RECORDED')?.decision,
    ) === 'ESTABLISH_EVIDENCE'
      ? establishedSummary(events)
      : '';
    return {
      visible: true,
      kind: 'released',
      headline: 'Released into usable inventory',
      tone: 'released',
      lines: [result?.reason || 'Every governing requirement was met by applicable evidence.'],
      context: established
        ? `Quality established ${established} as controlling.`
        : undefined,
      chip: { label: 'RELEASED', tone: 'released' },
    };
  }

  // The deterministic reason, in words. `failureProse` returns null when the
  // engine's clauses do not parse, and the raw reason stands rather than a
  // fabricated summary.
  const basis = str(computed?.basis) || undefined;
  const prose = failureProse(
    Array.isArray(computed?.failures) ? (computed.failures as DispositionFailure[]) : undefined,
    basis,
  );
  // ONE line. The readiness transitions and the executed recovery used to be
  // appended here as extra sentences, which is what made the frame restate
  // C-417/C-418 three times over. They are one compact strip now (`impact`),
  // and the full per-candidate detail stays in the completed Consequence
  // stage where an operator can open it deliberately.
  const lines = [prose || result?.reason || 'The evidence could not defend a release.'];

  return {
    visible: true,
    kind: blocked.length ? 'quarantined_with_consequence' : 'released',
    headline: 'Quarantined',
    tone: 'quarantine',
    lines,
    context: supersededContext(events, basis),
    nextAction: nextActionFrom(consequence),
    impact: impactFrom(consequence),
    chip: { label: 'QUARANTINED', tone: 'quarantine' },
  };
}

/**
 * Why a document that looks acceptable on its face still failed.
 *
 * Sourced from what the investigator actually did: `list_candidate_specs`
 * returned more than one revision of the governing spec and the brief resolved
 * a different one than the certificate cites. Both halves are in the event
 * stream, so this states a fact the record can back.
 *
 * The certificate's own declared revision is NOT available here — the BFF
 * surfaces `claim_count` but never the claims — so this deliberately says
 * "considered and not selected" rather than putting a CONFORMS claim in the
 * supplier's mouth that the payload cannot evidence.
 */
function supersededContext(
  events: LifecycleEventDTO[],
  basis: string | undefined,
): string | undefined {
  if (!basis) return undefined;
  const candidates = allOf(events, 'TOOL_RESULT_BOUND')
    .filter((e) => str(e.tool) === 'list_candidate_specs')
    .flatMap((e) => (Array.isArray(e.object_refs) ? (e.object_refs as string[]) : []));
  const others = [...new Set(candidates)].filter((r) => r && r !== basis);
  if (!others.length) return undefined;

  // One short line, not a retelling. The failure sentence above already names
  // the governing revision inside the requirement clause, so repeating which
  // revisions lost is noise — this only has to establish that the governing
  // one WAS chosen from several, and the full comparison lives in the
  // completed Investigator/Reconciliation detail.
  return `${basis.replace(':', ' Rev ')} is the governing requirement.`;
}

/**
 * What the operator does next, stated only when a gap actually remains.
 *
 * Derived from the readiness the recalculation produced, never from a fixture:
 * an order still BLOCKED after recovery ran is an open gap. If recovery closed
 * everything, there is nothing to tell the operator and this returns undefined
 * rather than manufacturing a task.
 */
function nextActionFrom(consequence: ConsequenceVM | null): string | undefined {
  if (!consequence) return undefined;
  const stillBlocked = consequence.metrics.filter((m) => m.value === 'BLOCKED');
  if (!stillBlocked.length) return undefined;

  // Two imperatives, because the operator has two things to do and the second
  // one is the recovery the engine already authorized. The selected candidate
  // is the engine's own choice — read, never inferred from order id — so this
  // stays silent about "begin" when recovery found nothing to move.
  const selected = consequence.candidates.find((c) => c.selected);
  const stop = stillBlocked.map((m) => `Block ${m.label}.`).join(' ');
  return selected ? `${stop} Begin ${selected.candidateId}.` : stop;
}

/**
 * The compact production-impact strip: what the schedule now looks like.
 *
 * Separate from `nextAction` deliberately. The action is what a human does;
 * this is what already happened to the plan, and collapsing them produced the
 * duplicated C-417/C-418 explanations this frame used to carry.
 */
function impactFrom(consequence: ConsequenceVM | null): string | undefined {
  if (!consequence) return undefined;
  const blocked = consequence.readinessChanges
    .filter((c) => c.to === 'BLOCKED')
    .map((c) => `${c.orderId} blocked`);
  const selected = consequence.candidates.find((c) => c.selected);
  const moved = selected && consequence.executed
    ? [`${selected.candidateId} moved into the available production slot`]
    : [];
  const parts = [...blocked, ...moved];
  return parts.length ? `${parts.join(' · ')}.` : undefined;
}

function truthFrom(
  events: LifecycleEventDTO[],
  lotId: string,
  material: string,
): EstablishedTruthVM {
  const brief = last(events, 'APPLICABILITY_BRIEF_COMPLETED');
  const binding = last(events, 'EVIDENCE_BINDING_COMPLETED');
  const mutation = last(events, 'MUTATION_COMPLETED');

  return {
    lotLine: [lotId, material].filter(Boolean).join(' · '),
    // Deliberately null until the brief lands: showing a placeholder would
    // imply the basis was known before it was resolved.
    governingBasis: brief ? str(brief.basis) || null : null,
    // The bound IDENTITY, not the binding status. The column renders this
    // under a "BOUND FACT" heading, so `binding_status` put the word "BOUND"
    // under the label "BOUND FACT" and told the operator nothing. Which lot the
    // document actually bound to is the fact worth showing — and on the hostile
    // path it is the only thing Vouch established before it stopped.
    boundFact: (() => {
      if (!binding || !bool(binding.bound)) return null;
      const claimed = (binding.claimed_identity ?? {}) as Record<string, unknown>;
      const lot = str(claimed.claimed_lot);
      return lot
        ? { label: 'Identity bound', value: lot }
        : { label: 'Identity bound', value: str(binding.binding_status, 'BOUND') };
    })(),
    holdTruth: mutation ? `${titleCase(str(mutation.action))} committed` : null,
  };
}

/**
 * The sufficiency ONE agent asserted, from its own persisted brief.
 *
 * `record.<role>.brief` is the complete brief (`AgentSegment.brief`, added so a
 * reviewer sees what was asserted and not merely its hash).
 *
 * THIS IS A REPLAY FALLBACK, NOT THE LIVE PATH. Both completion events now
 * publish `sufficiency` (`agents.py`), so a live run resolves either lane from
 * the event stream the moment that agent finishes. This remains because it is
 * the ONLY thing that can answer for a decision recorded BEFORE that change:
 * every captured run in `__tests__` emits `VERIFIER_BRIEF_COMPLETED` carrying
 * `brief_hash` alone, and Records/Today replay those through the same
 * `project()`. Deleting it would blank the verifier lane on historical
 * decisions.
 *
 * It must therefore stay BELOW the event in the lane's fallback order. Above
 * it, a stored record would win over the live event and reintroduce the exact
 * ordering bug this change fixed — a lane that cannot resolve until the
 * terminal record loads reads as unfinished until after the outcome is on
 * screen.
 *
 * Strictly per-role: the verifier's value comes from the verifier's own brief
 * or it stays null. A lane that borrowed the investigator's answer would make
 * an independent verifier look like it agreed when it was never asked.
 */
function briefSufficiency(
  record: Record<string, unknown> | null | undefined,
  role: 'investigator' | 'verifier',
): string | null {
  const segment = (record?.[role] ?? null) as Record<string, unknown> | null;
  const brief = (segment?.brief ?? null) as Record<string, unknown> | null;
  const value = brief ? str(brief.sufficiency) : '';
  return value || null;
}

/**
 * What this agent actually SELECTED, when that is the thing in dispute.
 *
 * The lanes normally show `sufficiency`, which answers "is every requirement
 * covered". On a MATERIAL_DISAGREEMENT that is the one field both agents
 * agree on — they each found applicable evidence — so two cards read
 * "Evidence covers the requirement" side by side under a banner saying they
 * disagreed. The screen asserted agreement and disagreement at once, and hid
 * the only dimension that actually differed.
 *
 * So when the briefs disagree, the lane states the chosen measurement and how
 * it is authorized. Roles are NOT assumed: live Nova has been observed taking
 * either path, so whatever each agent selected is what its own card shows.
 *
 * Returns null when there is no disagreement or no resolvable selection, and
 * the lane falls back to sufficiency — the ordinary case, unchanged.
 */
function briefSelection(
  record: Record<string, unknown> | null | undefined,
  role: 'investigator' | 'verifier',
  reconciliation: ReconciliationVM | null,
): string | null {
  if (reconciliation?.state !== 'MATERIAL_DISAGREEMENT') return null;

  const segment = (record?.[role] ?? null) as Record<string, unknown> | null;
  const brief = (segment?.brief ?? null) as Record<string, unknown> | null;
  const coverage = (brief?.coverage ?? []) as Record<string, unknown>[];
  if (!Array.isArray(coverage) || coverage.length === 0) return null;

  // The first row that actually resolves evidence. The reconciliation names
  // the differing FINGERPRINT FIELD (`coverage`), not a characteristic, so it
  // cannot narrow this further — and a brief that covers several requirements
  // still leads with the one it resolved.
  const row = coverage.find((c) => c.evidence_ref);
  if (!row) return null;

  const claim = claimById(record, str(row.evidence_ref));
  if (!claim) return null;

  const value = claim.value === null || claim.value === undefined ? '' : String(claim.value);
  const amount = [value, str(claim.units)].filter(Boolean).join(' ');
  const equivalence = str(row.equivalence_record_id);
  const route = equivalence ? `via ${equivalence}` : 'direct method';

  return [amount, str(claim.method), str(claim.condition)]
    .filter(Boolean)
    .join(' · ')
    .concat(` — ${route}`);
}

/** One frozen claim from the record's own canonical claim list. */
function claimById(
  record: Record<string, unknown> | null | undefined,
  claimId: string,
): Record<string, unknown> | null {
  if (!claimId) return null;
  const evidence = (record?.evidence ?? null) as Record<string, unknown> | null;
  const claims = (evidence?.canonical_claims ?? []) as Record<string, unknown>[];
  if (!Array.isArray(claims)) return null;
  return claims.find((c) => str(c.claim_id) === claimId) ?? null;
}

function spineFrom(
  events: LifecycleEventDTO[],
  active: StageKey | null,
  reconciliation: ReconciliationVM | null,
  record?: Record<string, unknown> | null,
  /**
   * The PROJECTED consequence, not the last raw event.
   *
   * A recovery pass emits its own CONSEQUENCE_RECALCULATED, so `last()` was
   * returning C-418's READY and the spine announced "READY · C-418" — a green
   * node that read as a successful decision and hid the quarantine's actual
   * impact. The projection already knows which order stopped and which one
   * moved; the spine now says the same thing.
   */
  consequenceVM?: ConsequenceVM | null,
): SpineNodeVM[] {
  const halted = securityHalted(events);
  const snapshot = last(events, 'EVIDENCE_SNAPSHOT_CREATED');
  const investigator = last(events, 'APPLICABILITY_BRIEF_COMPLETED');
  const verifier = last(events, 'VERIFIER_BRIEF_COMPLETED');
  const computed = last(events, 'DISPOSITION_COMPUTED');
  const qdr = openQualityDecision(events);
  const consequence = last(events, 'CONSEQUENCE_RECALCULATED');

  const evidenceState: SpineNodeVM['state'] = halted
    ? 'halted'
    : snapshot
      ? 'completed'
      : active === 'evidence'
        ? 'active'
        : events.length
          ? 'active'
          : 'pending';

  // A halted node reads HALTED, not PENDING. "Pending" tells an operator the
  // agents are still coming; on a security quarantine they are never going to
  // run, and that difference is the whole point of the hostile path.
  const agentsState: SpineNodeVM['state'] = halted
    ? 'halted'
    : reconciliation?.state === 'MATERIAL_DISAGREEMENT'
      ? 'material_disagreement'
      : verifier && investigator
        ? 'completed'
        : active === 'investigator' || active === 'verifier' || active === 'reconciliation'
          ? 'active'
          : 'pending';

  const dispositionState: SpineNodeVM['state'] = halted
    ? 'halted'
    : qdr
      ? 'material_disagreement'
      : computed
        ? 'terminal'
        : active === 'disposition'
          ? 'active'
          : 'pending';

  // A halted decision has no pending consequence. Nothing downstream of a
  // security quarantine is still coming, so rendering PENDING there would
  // promise a state change that will never arrive.
  const consequenceState: SpineNodeVM['state'] = halted
    ? 'halted'
    : consequence
      ? 'completed'
      : active === 'consequence'
        ? 'active'
        : 'pending';

  return [
    {
      key: 'evidence',
      label: 'Evidence',
      state: evidenceState,
      headline: halted ? 'Prompt injection' : snapshot ? 'Frozen' : 'Arriving',
      note: halted
        ? 'quarantined by Amazon Bedrock Guardrails'
        : snapshot
          ? `${num(snapshot.claim_count) ?? 0} claims`
          : '',
      // An explicit tone is what makes the node render its OWN headline
      // rather than nodePill's generic "⊘ HALTED". Each halted node states
      // the specific fact it knows; three identical HALTED pills would tell
      // the operator nothing about which stage stopped or why.
      tone: halted ? 'quarantine' : undefined,
    },
    {
      key: 'agents',
      label: 'Investigation & Verification',
      state: agentsState,
      headline: halted
        ? 'Not started'
        : reconciliation?.state === 'MATERIAL_DISAGREEMENT'
          ? 'Material disagreement'
          : verifier && investigator
            ? 'Independently reconciled'
            : 'Reasoning',
      note: halted ? 'no agent reasoning ran' : investigator ? str(investigator.basis) : '',
      // Priority: the specific evidence this agent SELECTED, then its own
      // completion EVENT, then its stored brief, then a progress state. Null
      // until one of them answers — the model documents these as
      // null-until-known, never a placeholder.
      //
      // On a disagreement the lane states what this agent SELECTED, because
      // that is what differs; otherwise it states sufficiency.
      //
      // The EVENT tier must stay above the record tier. Both completion events
      // now publish `sufficiency`, so each lane resolves the moment its own
      // agent finishes — mid-run, with no record in existence. `briefSufficiency`
      // sits below it purely to replay decisions recorded before that was true;
      // see its doc comment. Promoting the record above the event would restore
      // the bug where a lane stayed unresolved until the terminal fetch and so
      // appeared to fill in AFTER the disposition it actually preceded.
      //
      // On a halt both lanes state NOT_STARTED rather than the em-dash the
      // model uses for "not known yet". The two are different facts: one is
      // still coming, the other never will.
      //
      // The final fallback is IN_PROGRESS once the agent's STARTED event has
      // landed. The Verifier runs ALONE for as long as the model takes — a
      // measured 13.4s on the Hero A capture — and until its brief arrives the
      // lane read as the em-dash "nothing known", identical to a stage that
      // never ran. Then the brief, the reconciliation, the disposition and the
      // consequence all landed inside ~500ms, so verification appeared to be
      // filled in after the outcome rather than before it.
      //
      // This asserts nothing about the finding: it states only that the agent
      // is running, which is exactly what VERIFIER_STARTED establishes. The
      // em-dash still shows before the agent starts, and NOT_STARTED still
      // shows on a halt.
      //
      // The `&& !verifier` guard is load-bearing and was caught by test: the
      // COMPLETED event must veto this, or a FINISHED agent whose brief simply
      // has not been fetched yet (a stored record still loading, as in the
      // hero-b run-1 fixture) reads "Reasoning independently" — claiming a
      // completed agent is still working. Started-and-not-completed is the
      // only state this may describe.
      investigatorLane: halted
        ? 'NOT_STARTED'
        : briefSelection(record, 'investigator', reconciliation) ||
          (investigator ? str(investigator.sufficiency) : '') ||
          briefSufficiency(record, 'investigator') ||
          (last(events, 'INVESTIGATOR_STARTED') && !investigator ? 'IN_PROGRESS' : null),
      verifierLane: halted
        ? 'NOT_STARTED'
        : briefSelection(record, 'verifier', reconciliation) ||
          (verifier ? str(verifier.sufficiency) : '') ||
          briefSufficiency(record, 'verifier') ||
          (last(events, 'VERIFIER_STARTED') && !verifier ? 'IN_PROGRESS' : null),
      tone: halted ? 'quarantine' : undefined,
      reconciliationSeal: halted
        ? 'halted'
        : reconciliation
          ? reconciliation.state === 'MATERIAL_DISAGREEMENT'
            ? 'disagreement'
            : 'match'
          : 'pending',
    },
    {
      key: 'disposition',
      label: 'Disposition',
      state: dispositionState,
      headline: halted
        ? 'None'
        : qdr
          ? 'Quality decision'
          : str(computed?.disposition) || 'Pending',
      note: halted ? 'no disposition was made' : computed ? str(computed.basis) : '',
      tone: halted ? 'quarantine' : undefined,
    },
    consequenceNode(consequenceState, consequence, consequenceVM),
  ];
}

/**
 * The Consequence spine node: what the disposition did to the plan.
 *
 * States the blocked order as the headline and the recovery as supporting
 * detail, because that is the causal order — an order stopped, and another
 * one filled the gap. Falls back to the raw event only when no projection
 * exists (mid-run, before the recalculation lands).
 */
function consequenceNode(
  state: SpineNodeVM['state'],
  raw: LifecycleEventDTO | undefined,
  vm: ConsequenceVM | null | undefined,
): SpineNodeVM {
  const blocked = vm?.readinessChanges.filter((c) => c.to === 'BLOCKED') ?? [];
  const moved = vm?.candidates.find((c) => c.selected);

  // A security halt produces no consequence because it produced no
  // disposition. "NO MUTATION" is the fact; "Pending" would be a forecast.
  if (state === 'halted') {
    return {
      key: 'consequence',
      label: 'Consequence',
      state,
      headline: 'No mutation',
      note: 'no production state changed',
      tone: 'quarantine',
    };
  }

  if (blocked.length) {
    return {
      key: 'consequence',
      label: 'Consequence',
      state,
      headline: `${blocked.map((c) => c.orderId).join(', ')} blocked`,
      // Supporting recovery information, deliberately the note and not the
      // headline: C-418 being fine is not the consequence of a quarantine.
      note: moved && vm?.executed ? `${moved.candidateId} moved into its slot` : '',
      // Rust, not green. An order stopped.
      tone: 'quarantine',
    };
  }

  return {
    key: 'consequence',
    label: 'Consequence',
    state,
    headline: raw ? str(raw.order_readiness) || 'Recalculated' : 'Pending',
    note: raw ? str(raw.order_id) : '',
  };
}

function completedFrom(
  events: LifecycleEventDTO[],
  active: StageKey | null,
  parts: {
    investigator: AgentStageVM | null;
    verifier: AgentStageVM | null;
    reconciliation: ReconciliationVM | null;
    disposition: DispositionVM | null;
    consequence: ConsequenceVM | null;
  },
): CompletedStageVM[] {
  if (!active) return [];
  const activeIndex = STAGE_ORDER.indexOf(active);
  const out: CompletedStageVM[] = [];

  const snapshot = last(events, 'EVIDENCE_SNAPSHOT_CREATED');
  const add = (
    stageKey: StageKey,
    title: string,
    oneLine: string,
    pill: { label: string; tone: SemanticTone },
    runNumber?: number,
  ) => {
    if (STAGE_ORDER.indexOf(stageKey) < activeIndex)
      out.push({ stageKey, title, oneLine, pill, runNumber });
  };

  add(
    'evidence',
    'Evidence',
    snapshot ? `${num(snapshot.claim_count) ?? 0} claims frozen` : 'Evidence received',
    { label: 'FROZEN', tone: 'progress' },
  );
  if (parts.investigator)
    add(
      'investigator',
      'Applicability Investigator',
      parts.investigator.resultTitle,
      { label: parts.investigator.sufficiency ?? 'DONE', tone: parts.investigator.resultTone },
      parts.investigator.runNumber,
    );
  if (parts.verifier)
    add(
      'verifier',
      'Independent Verifier',
      parts.verifier.resultTitle,
      { label: parts.verifier.sufficiency ?? 'DONE', tone: parts.verifier.resultTone },
      parts.verifier.runNumber,
    );
  if (parts.reconciliation)
    add('reconciliation', 'Reconciliation', parts.reconciliation.note, {
      label: parts.reconciliation.state,
      tone: parts.reconciliation.state === 'MATERIAL_DISAGREEMENT' ? 'refused' : 'released',
    });
  if (parts.disposition)
    add('disposition', 'Disposition', parts.disposition.disposition, {
      label: parts.disposition.disposition || 'PENDING',
      tone: parts.disposition.tone,
    });
  if (parts.consequence) {
    const blocked = parts.consequence.readinessChanges.filter((c) => c.to === 'BLOCKED').length;
    const moved = parts.consequence.executed
      ? parts.consequence.candidates.find((c) => c.selected)
      : undefined;
    add(
      'consequence',
      'Consequence',
      // The one-line summary of what the grid contains, so reopening it is a
      // deliberate act rather than the default state.
      `${parts.consequence.candidates.length} recovery options evaluated`,
      {
        // Names the order that moved. "RECOVERED" was generic enough that a
        // viewer had to open the grid to learn what actually happened.
        label: moved
          ? `${moved.candidateId} MOVED UP`
          : blocked
            ? 'BLOCKED'
            : 'EVALUATED',
        tone: moved ? 'released' : blocked ? 'refused' : 'progress',
      },
    );
  }

  return out;
}

export interface ProjectInput {
  decisionRecordId: string;
  lotId: string;
  material?: string;
  receiptMeta?: string;
  events: LifecycleEventDTO[];
  /** The terminal authoritative response, once it has landed. */
  result?: EvaluateDTO | null;
  sources?: SourceArtifactDTO[];
  /**
   * The stored decision document from `get_decision`, when it has landed.
   * Carries `evidence.canonical_claims` — the only authoritative surface that
   * itemizes what was extracted.
   */
  record?: Record<string, unknown> | null;
  selectedArtifactId?: string | null;
  running?: boolean;
  failure?: FailureVM | null;
  durable?: boolean;
}

/** The one projection. Everything the workspace renders comes from here. */
/** The quality-authority segment off a stored record, narrowed once. */
function qualityAuthorityOf(
  record: Record<string, unknown> | null | undefined,
): QualityAuthorityDTO | undefined {
  const segment = record?.quality_authority;
  return segment ? (segment as QualityAuthorityDTO) : undefined;
}

/** How many measurements were extracted but held pending identity. */
function heldClaimCountOf(record: Record<string, unknown> | null | undefined): number {
  const security = (record?.security ?? {}) as Record<string, unknown>;
  return num(security.held_claim_count) ?? 0;
}

//: The canonical role names. "Verifier" alone reads as a generic checker; the
//: architecture's whole claim is that the second read is INDEPENDENT, and the
//: name is where an operator learns that.
const AGENT_LABEL: Record<string, string> = {
  INVESTIGATOR: 'Investigator',
  VERIFIER: 'Independent Verifier',
};

/** "470 MPa by ASTM-E8 at room_temp" — the operator's own vocabulary. */
function measurementOf(option: {
  value?: number | string | null;
  units?: string;
  method?: string;
  condition?: string;
}): string {
  const value = option.value === null || option.value === undefined ? '' : String(option.value);
  const amount = [value, str(option.units)].filter(Boolean).join(' ');
  const method = str(option.method);
  const condition = str(option.condition);
  const how = [method && `by ${method}`, condition && `at ${condition}`]
    .filter(Boolean)
    .join(' ');
  return [amount, how].filter(Boolean).join(' ');
}

/**
 * §8. The disputed question, ready to answer — or null.
 *
 * Null whenever there is nothing to ask OR the question has already been
 * answered. That is what makes the affordance disappear: the panel is not
 * hidden by a flag, it ceases to exist in the projection.
 */
export function qualityPanelFrom(
  authority: QualityAuthorityDTO | undefined,
): QualityAuthorityPanelVM | null {
  const question = authority?.question;
  if (!question?.question_id) return null;
  // One panel per question type. Without this an identity question would fall
  // through into the measurement panel and render a question about viscosity
  // that nobody asked.
  if (str(question.question_type) !== 'EVIDENCE_APPLICABILITY') return null;
  if (str(question.status) !== 'OPEN') return null;
  if ((authority?.decisions ?? []).length > 0) return null;

  const options: QualityAuthorityOptionVM[] = (question.options ?? []).map((o) => {
    const equivalence = str(o.equivalence_id);
    const passes = o.within_limits === true;
    const threshold = str(o.threshold);
    return {
      claimId: str(o.claim_id),
      selectedBy: str(o.selected_by) === 'VERIFIER' ? 'VERIFIER' : 'INVESTIGATOR',
      agentLabel: AGENT_LABEL[str(o.selected_by)] ?? str(o.selected_by),
      measurement: measurementOf(o),
      basis: equivalence
        ? `applicable via ${equivalence}`
        : `the method ${str(question.method_to)} names`,
      routeLabel: equivalence ? `VIA ${equivalence}` : 'DIRECT METHOD',
      value: [
        o.value === null || o.value === undefined ? '' : String(o.value),
        str(o.units),
      ]
        .filter(Boolean)
        .join(' '),
      methodLine: [str(o.method), str(o.condition)].filter(Boolean).join(' · '),
      // The same verb on both cards. A label that named the method made the
      // two buttons different lengths and invited reading one as the primary
      // action; the choice is between the cards, not between the buttons.
      actionLabel: 'Establish this evidence',
      // The requirement, NOT the disposition it would produce.
      //
      // The card used to read "If established: deterministic result = RELEASE"
      // (and QUARANTINE on the other). That pre-announced the outcome of a
      // choice the human has not made yet, which turns an authority question
      // into a pair of labelled buttons: an operator reads RELEASE vs
      // QUARANTINE and picks the outcome they want, rather than deciding which
      // MEASUREMENT actually governs — the only question they are being asked.
      //
      // The measurement, its method, its route and the requirement it is judged
      // against are all still on the card. The disposition follows
      // deterministically from whichever evidence is established, so stating it
      // here adds nothing the gate does not already compute.
      consequence: threshold ? `Requirement ${threshold}` : '',
      passes,
    };
  });

  const characteristic = str(question.characteristic).replace(/_/g, ' ');
  const equivalenceId = str(question.equivalence_id);
  // The exact sentence. Every noun in it is a backend fact.
  // "Which", not "whether". The two paths lead to different dispositions, so
  // the operator is choosing between them rather than ratifying one.
  //
  // Deliberately short and free of mechanism: an operator answering this does
  // not need to know what a material fingerprint is, and the cards below
  // carry the methods, the routes and the consequences.
  const question_text = `Which ${characteristic} result should control this decision?`;

  const position = (o: QualityAuthorityOptionVM | undefined): string =>
    o ? `${o.value} · ${o.methodLine} · ${o.routeLabel}` : '';

  return {
    questionId: str(question.question_id),
    question: question_text,
    characteristic: str(question.characteristic),
    equivalenceId,
    options,
    investigatorPosition: position(options.find((o) => o.selectedBy === 'INVESTIGATOR')),
    verifierPosition: position(options.find((o) => o.selectedBy === 'VERIFIER')),
    // Why a human is here, in one sentence. The mechanism — reconciliation,
    // fingerprints, equivalence scope — stays out of the operator's way; it is
    // all still in the record for an auditor.
    disputed:
      'The Investigator and Independent Verifier selected different valid evidence.',
    // Deliberately NOT "Approve"/"Release". Establishing evidence names which
    // measurement is controlling; holding leaves the lot where it is. Neither
    // verb decides the lot.
    holdActionLabel: 'Keep held',
  };
}

/**
 * The identity question, ready to answer — or null.
 *
 * Every noun the operator reads is a backend fact: the supplier's own batch
 * id, the internal lot id, the artifact hash. The frontend composes the
 * sentence and invents none of it.
 */
export function identityPanelFrom(
  authority: QualityAuthorityDTO | undefined,
  input?: { heldClaimCount?: number },
): IdentityBindingPanelVM | null {
  const question = authority?.question;
  if (!question?.question_id) return null;
  if (str(question.question_type) !== 'IDENTITY_BINDING') return null;
  if (str(question.status) !== 'OPEN') return null;
  if ((authority?.decisions ?? []).length > 0) return null;

  const batch = str(question.supplier_batch);
  const lotId = str(question.internal_lot_id);
  const held = input?.heldClaimCount ?? 0;

  return {
    questionId: str(question.question_id),
    // The exact question, and it is only about identity. Not "approve", not
    // "accept evidence", not "release" — the human is confirming who this
    // document belongs to, and nothing else.
    question: `Does supplier batch ${batch} correspond to internal ${lotId} for this evidence?`,
    reason:
      `The certificate was read successfully, but supplier batch ${batch} is ` +
      `not authoritatively linked to internal lot ${lotId}.`,
    // Stated POSITIVELY, because the failure mode of this screen is being
    // mistaken for an OCR failure. Everything that DID work is named.
    verified: [
      { label: 'Document', value: 'Parsed successfully' },
      {
        label: 'Measurements',
        value: held ? `${held} extracted` : 'Extracted',
      },
      { label: 'Security', value: 'Passed' },
    ],
    supplierSide: {
      heading: 'SUPPLIER DOCUMENT',
      identifier: `Batch ${batch}`,
      detail: [str(question.supplier_id), str(question.supplier_site)]
        .filter(Boolean)
        .join(' · '),
    },
    vouchSide: {
      heading: 'VOUCH',
      identifier: lotId,
      detail: [str(question.material_id), str(question.po_reference)]
        .filter(Boolean)
        .join(' · '),
    },
    mappingStatus: 'Mapping not established',
    // Identity verbs on both actions. Neither decides the lot: confirming
    // establishes a correspondence and the engine still computes the outcome.
    confirmLabel: 'Confirm binding',
    confirmDetail: `Establish that batch ${batch} is ${lotId} for this decision`,
    keepUnboundLabel: 'Keep unbound',
    keepUnboundDetail: 'Retain the evidence without attaching it to this lot',
    supplierBatch: batch,
    internalLotId: lotId,
    artifactId: str(question.artifact_id),
    contentHash: str(question.content_hash),
  };
}

/** §8. The durable stage that replaces the panel once a human has answered. */
export function qualityAuthorityFrom(
  authority: QualityAuthorityDTO | undefined,
): QualityAuthorityRecordVM | null {
  const decisions = authority?.decisions ?? [];
  if (decisions.length === 0) return null;
  const decision: HumanAuthorityDecisionDTO = decisions[decisions.length - 1];
  const verb = str(decision.decision);

  // The identity authority is its own completed stage. It answers a different
  // question, so it says a different thing — never "evidence established".
  if (verb === 'CONFIRM_BINDING' || verb === 'KEEP_UNBOUND') {
    const batch = str(decision.supplier_batch);
    const boundLot = str(decision.bound_lot_id);
    const confirmed = verb === 'CONFIRM_BINDING';
    return {
      decision: confirmed ? 'CONFIRM_BINDING' : 'KEEP_UNBOUND',
      headline: confirmed ? 'Identity authority' : 'Kept unbound',
      tone: confirmed ? 'released' : 'atrisk',
      question: `Does supplier batch ${batch} correspond to internal ${boundLot} for this evidence?`,
      answer: confirmed
        ? `Supplier batch ${batch} confirmed as ${boundLot}`
        : `Evidence retained; batch ${batch} was not attached to ${boundLot}`,
      accountableActor: str(decision.accountable_actor),
      authoritySource: str(decision.authority_source),
      timestamp: str(decision.created_at),
      clock: clockOf(str(decision.created_at)),
      // The ARTIFACT is what this authority is bound to, not a claim set: the
      // human confirmed a correspondence for specific bytes they were shown.
      snapshotBinding: str(decision.content_hash).slice(0, 12),
      answerLabel: 'Established',
      bindingLabel: 'Source artifact',
      stageLabel: 'Identity authority',
    };
  }

  const authorized = verb === 'ESTABLISH_EVIDENCE';
  const characteristic = str(decision.characteristic).replace(/_/g, ' ');

  return {
    decision: authorized ? 'ESTABLISH_EVIDENCE' : 'KEEP_HELD',
    headline: authorized ? 'Controlling evidence established' : 'Kept held',
    tone: authorized ? 'released' : 'atrisk',
    question: qualityQuestionText(decision),
    // What was established, in the operator's own terms. The backend records
    // the measurement alongside the claim id precisely so this line does not
    // have to name an opaque reference months later.
    // One line an operator can read at a glance: what controls this decision.
    answer: authorized
      ? [
          [decision.established_value ?? '', str(decision.established_units)]
            .filter(Boolean)
            .join(' '),
          str(decision.established_method),
          str(decision.established_via_equivalence)
            ? `via ${str(decision.established_via_equivalence)}`
            : 'direct method',
        ]
          .filter(Boolean)
          .join(' · ')
          .concat(' established as controlling')
      : `Lot kept held; no ${characteristic} determination was established`,
    accountableActor: str(decision.accountable_actor),
    authoritySource: str(decision.authority_source),
    timestamp: str(decision.created_at),
    clock: clockOf(str(decision.created_at)),
    snapshotBinding: str(decision.claim_set_hash).slice(0, 12),
    answerLabel: 'Established',
    bindingLabel: 'Evidence snapshot',
    stageLabel: 'Quality authority',
  };
}

function qualityQuestionText(decision: HumanAuthorityDecisionDTO): string {
  const characteristic = str(decision.characteristic).replace(/_/g, ' ');
  const equivalenceId = str(decision.equivalence_id);
  if (!equivalenceId) {
    return `Does Quality authorize the disputed ${characteristic} evidence as applicable for this decision?`;
  }
  return (
    `Does Quality authorize ${equivalenceId} — ${str(decision.method_from)} in place of ` +
    `${str(decision.method_to)} at ${str(decision.condition)} — as applicable to the ` +
    `${characteristic} requirement for this decision?`
  );
}

/**
 * Events the MAIN CANVAS may project from.
 *
 * The causal invariant: while the Verifier is visibly still reasoning, nothing
 * downstream of it may read as resolved — not the reconciliation seal, not the
 * disposition, not the consequence, not the terminal outcome. A frame showing
 * "Reasoning independently" beside a committed RELEASE is causally impossible
 * and reads as a broken product.
 *
 * Polling is what makes this reachable. Events arrive in ~900ms batches, and a
 * verifier that finishes 8s into a batch lands its completion event alongside
 * the reconciliation, disposition and consequence that followed it. If the
 * verifier's own event cannot RESOLVE the lane, the canvas renders an
 * unresolved verifier beside a finished decision.
 *
 * Both roles now publish `sufficiency`, so a current runtime resolves the lane
 * from that event and this gate never fires. It exists for the case the payload
 * cannot cover: a runtime deployed before that change, and the stored records
 * it already wrote. There the lane resolves only when the terminal record
 * loads, which is strictly after the outcome.
 *
 * This withholds PRESENTATION of events that genuinely happened; it invents
 * nothing, delays nothing on a timer, and reorders nothing. The moment the
 * verifier becomes resolvable the full stream projects. The activity rail is
 * deliberately NOT gated — it is the audit chronology and must show real events
 * as they arrive.
 */
const DOWNSTREAM_OF_VERIFIER = new Set([
  'RECONCILIATION_COMPLETED',
  'DISPOSITION_COMPUTED',
  'QUALITY_DECISION_REQUIRED',
  'POLICY_EVALUATED',
  'CAPABILITY_ISSUED',
  'MUTATION_COMPLETED',
  'CONSEQUENCE_RECALCULATED',
  'READINESS_TRANSITIONED',
  'RECOVERY_EVALUATED',
  'RECOVERY_EXECUTED',
]);

/**
 * The Verifier has finished AND the canvas can say what it found.
 *
 * `VERIFIER_BRIEF_COMPLETED` alone is not enough: an event that states no
 * `sufficiency` leaves the lane unresolved, which is the whole failure this
 * gate exists to prevent. Resolvable means the lane can render a finding — from
 * the event itself, or from a stored brief that has already landed.
 *
 * True when the verifier has not started, because then there is nothing
 * downstream of it to hold.
 */
function verifierResolved(
  events: LifecycleEventDTO[],
  record: Record<string, unknown> | null | undefined,
): boolean {
  if (securityHalted(events)) return true; // no verification will ever run
  const started = last(events, 'VERIFIER_STARTED');
  if (!started) return true;
  const done = last(events, 'VERIFIER_BRIEF_COMPLETED');
  if (!done) return false;
  return Boolean(str(done.sufficiency) || briefSufficiency(record, 'verifier'));
}

/**
 * Whether the causal gate applies to THIS frame.
 *
 * Only while the decision is being watched. The gate protects the ORDER events
 * appear in as they stream, and a settled decision has no order left to
 * protect — every stage is already known.
 *
 * This distinction is load-bearing, and testing found it. Most captured runs
 * carry a verifier event with no `sufficiency` AND no stored verifier brief, so
 * a gate that also applied at rest would blank the disposition and outcome on
 * every historical decision, permanently — Records and Today would render a
 * finished, released lot as though nothing had been decided. That trades a
 * transient live-frame glitch for durable loss of the audit surface.
 *
 * So: live runs get causal ordering, settled records get completeness.
 */
function gateApplies(input: ProjectInput): boolean {
  return Boolean(input.running);
}

function canvasEvents(events: LifecycleEventDTO[]): LifecycleEventDTO[] {
  return events.filter((e) => !DOWNSTREAM_OF_VERIFIER.has(String(e.event)));
}

export function project(input: ProjectInput): DecisionWorkspaceVM {
  const all = [...input.events].sort(
    (a, b) => (num(a.sequence) ?? 0) - (num(b.sequence) ?? 0),
  );
  // The canvas projects from the causally-gated view; the rail uses `all`.
  const gate = gateApplies(input) && !verifierResolved(all, input.record);
  const events = gate ? canvasEvents(all) : all;
  /**
   * The authoritative response carries the disposition and mutation DIRECTLY,
   * so it walks straight past an event-list gate: the outcome panel and header
   * would announce RELEASE while the verifier still read as unresolved. It is
   * withheld on exactly the same condition, and for the same reason.
   *
   * A FAILURE is never withheld. A technical failure, a security halt or an
   * abstention is not downstream of the verifier — it is the reason there is no
   * verification to wait for, and hiding it would leave the frame silent.
   */
  const result = gate ? null : (input.result ?? null);
  const failure = input.failure ?? null;

  const active = activeStageFrom(events);
  const investigator = agentFrom(events, 'investigator');
  const verifier = agentFrom(events, 'verifier');
  const reconciliation = reconciliationFrom(events);
  const disposition = dispositionFrom(events, result);
  const consequence = consequenceFrom(events, result);

  const material = input.material ?? '';
  /**
   * The disposition the HEADER may claim.
   *
   * A proposal is not an outcome. On the abstain path the backend emits
   * `DISPOSITION_COMPUTED: QUARANTINE`, the policy gate then REFUSES it, and
   * `QUALITY_DECISION_REQUIRED` follows — no mutation is committed and the
   * decision stays open for a human.
   *
   * Reading the computed value straight through put "QUARANTINE" in the header
   * beside an outcome panel reading "Quality decision required · ABSTAIN": the
   * UI asserted a state change that was explicitly refused. While a quality
   * decision is outstanding the header states that, and nothing else.
   */
  const disp = disposition?.qualityDecisionRequired
    ? 'QUALITY DECISION'
    : (disposition?.disposition ?? result?.disposition ?? '');
  /**
   * The decision is finished and nothing is still being watched.
   *
   * `consequence` is the last stage, so reaching it with an authoritative
   * result and no run in flight IS the terminal frame. A quality decision
   * still awaiting a human is deliberately excluded — that frame has an open
   * question and must keep its stage visible.
   *
   * This no longer collapses the stage. Consequence is what the decision DID to
   * the factory, and folding it into the reopenable stack the instant it became
   * final meant the one answer the operator came for arrived and then hid
   * itself. It stays expanded; only the recovery grid inside it defers, which
   * is the part that actually competed with the outcome panel.
   */
  const terminal =
    active === 'consequence' &&
    Boolean(result) &&
    !input.running &&
    !disposition?.qualityDecisionRequired;
  const consequenceVM =
    consequence && terminal ? { ...consequence, deferCandidates: true } : consequence;

  // Claims live on the durable record, not on `get_source`. Joining here keeps
  // the itemization in one place rather than in each component that shows one.
  const joinedClaims = claimsByArtifact(input.record);

  return {
    decisionRecordId: input.decisionRecordId,
    lotId: input.lotId,
    material,
    receiptMeta: input.receiptMeta ?? '',
    // A technical failure must not render a disposition anywhere, including
    // the header pill.
    dispositionLabel: failure?.suppressesDisposition ? '' : disp,
    dispositionTone: dispositionTone(disp),
    running: Boolean(input.running),
    authoritative: Boolean(result),
    durable: input.durable ?? true,
    spine: spineFrom(events, active, reconciliation, input.record, consequence),
    outcome: outcomeFrom(events, result, failure),
    activeStage: active,
    // Still full-bleed at the terminal frame: the case-context column has
    // nothing left to add once the decision is final, and remounting it
    // duplicated the lot identity the header already carries.
    fullBleed: active ? FULL_BLEED.includes(active) : false,
    completed: completedFrom(events, active, {
      investigator,
      verifier,
      reconciliation,
      disposition,
      consequence,
    }),
    sources: (input.sources ?? []).map((a) => toSource(a, joinedClaims.get(str(a.artifact_id)))),
    /**
     * Whether an artifact is KNOWN to exist but has not been fetched yet.
     *
     * Read from the lifecycle, not from the fetch. `EVIDENCE_RECEIVED` is the
     * backend stating an artifact exists; `get_source` only becomes answerable
     * once the record is durable, which live running showed lands roughly three
     * seconds AFTER the outcome renders.
     *
     * Deriving this from `running` was not enough: by the time the terminal
     * source fetch resolves the run is already over, so the column claimed
     * "No source artifact yet" about a document that demonstrably existed.
     * Absence of a fetch is not absence of evidence.
     */
    sourcesPending:
      (input.sources ?? []).length === 0 &&
      (Boolean(last(events, 'EVIDENCE_RECEIVED')) || Boolean(input.running)),
    selectedArtifactId: input.selectedArtifactId ?? null,
    truth: truthFrom(events, input.lotId, material),
    investigator,
    verifier,
    reconciliation,
    disposition,
    consequence: consequenceVM,
    // `all`, never the gated view: the rail is the audit chronology and must
    // show real events as they arrive. The gate withholds CANVAS presentation
    // only — an audit surface that hid events would lie by omission.
    activity: toActivity(all).reverse(), // newest first (D7)
    failure,
    // One or the other, never both: an answered question has no panel, and an
    // unanswered one has no record. The control cannot outlive its decision.
    qualityAuthorityPanel: qualityPanelFrom(qualityAuthorityOf(input.record)),
    identityBindingPanel: identityPanelFrom(qualityAuthorityOf(input.record), {
      heldClaimCount: heldClaimCountOf(input.record),
    }),
    qualityAuthority: qualityAuthorityFrom(qualityAuthorityOf(input.record)),
    runBanner: runBannerFrom(events, input.record),
  };
}

/**
 * §7. "Run 2 · resumed after Quality authority", or null on a first run.
 *
 * Read from DECISION_RESUMED, which carries both the run number and WHY the
 * case continued — a human establishing controlling evidence and a human
 * supplying new evidence are different continuations and must not read the
 * same. Falls back to the record's own run_count so the banner survives a
 * reload after the events have scrolled out of the polling window.
 */
/** "312 cP · ASTM-D445 via EQV-1", from the recorded authority event. */
function establishedSummary(events: LifecycleEventDTO[]): string {
  const recorded = last(events, 'QUALITY_AUTHORITY_RECORDED');
  if (!recorded) return '';
  const value = [
    recorded.established_value === null || recorded.established_value === undefined
      ? ''
      : String(recorded.established_value),
    str(recorded.established_units),
  ]
    .filter(Boolean)
    .join(' ');
  const equivalence = str(recorded.established_via_equivalence);
  return [
    value,
    str(recorded.established_method),
    equivalence ? `via ${equivalence}` : 'direct method',
  ]
    .filter(Boolean)
    .join(' · ');
}

export function runBannerFrom(
  events: LifecycleEventDTO[],
  record?: Record<string, unknown> | null,
): string | null {
  const resumed = last(events, 'DECISION_RESUMED');
  const stored = num(record?.run_count) ?? 1;
  const run = resumed ? (num(resumed.run_count) ?? stored) : stored;
  if (run < 2) return null;

  const trigger = resumed ? str(resumed.trigger) : '';
  const because =
    trigger === 'QUALITY_AUTHORITY'
      ? 'resumed after Quality authority'
      : trigger === 'IDENTITY_BINDING'
        ? 'resumed after identity confirmation'
        : trigger === 'HUMAN_EVIDENCE'
          ? 'resumed after human evidence'
          : 'resumed';
  return `Run ${run} · ${because}`;
}
