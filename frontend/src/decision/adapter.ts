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
      return {
        short: 'Security inspection',
        summary: outcome === 'DETECTED' ? 'prompt attack detected' : `guardrail ${outcome.toLowerCase()}`,
      };
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
      return { short: 'Quality decision required', summary: str(e.reason) };
    case 'QUALITY_QUESTION_RAISED':
      return {
        short: 'Applicability question raised',
        summary: [str(e.equivalence_id), str(e.characteristic)].filter(Boolean).join(' · '),
      };
    case 'QUALITY_AUTHORITY_RECORDED':
      return {
        // The rail row the gate asks for: "QUALITY · Applicability authorized",
        // then "EQV-1 · LOT-1006 · QA-LEAD" underneath it.
        short:
          str(e.decision) === 'ESTABLISH_EVIDENCE'
            ? 'Controlling evidence established'
            : 'Kept held',
        summary: [str(e.equivalence_id), str(e.accountable_actor)]
          .filter(Boolean)
          .join(' · '),
      };
    case 'HUMAN_EVIDENCE_RECEIVED':
      return { short: 'Human evidence received', summary: str(e.authority_source) };
    case 'DECISION_RESUMED':
      return { short: 'Decision resumed', summary: `run ${num(e.run_number) ?? 2}` };
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
    case 'QUALITY_QUESTION_RAISED':
    case 'BRIEF_VALIDATION_FAILED':
      return 'caution';
    case 'QUALITY_AUTHORITY_RECORDED':
      return str(e.decision) === 'ESTABLISH_EVIDENCE' ? 'good' : 'caution';
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
    if (e.event === 'HUMAN_EVIDENCE_RECEIVED') {
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
    const actorType = ACTOR_BY_EVENT[e.event] ?? 'system';
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
    // The Verifier's completion event carries ONLY a brief hash — no basis and
    // no sufficiency — because the verifier is deliberately blind. Treating that
    // silence as "not sufficient" printed a flat contradiction: its own lane
    // read "Evidence covers the requirement" while this line said the opposite,
    // on a lot that released. Unknown is stated as unknown.
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
  // carries ONLY a brief hash — no basis, no sufficiency. That is the
  // verifier-blind architecture showing through the event surface, and it means
  // a side-by-side value table would have to source the Verifier's column from
  // somewhere it does not exist. Rather than fabricate one or borrow the
  // Investigator's, the comparison is shown as what the backend actually
  // computed: the reconciliation OUTCOME plus the fields it found differing.
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
  const qdr = last(events, 'QUALITY_DECISION_REQUIRED');
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
    return {
      visible: true,
      kind: 'evidence_quarantined',
      headline: 'Evidence quarantined before any decision was made',
      tone: 'quarantine',
      lines: [
        'The document was withheld from the decision agents entirely.',
        'The lot state was not changed.',
      ],
      chip: { label: 'SECURITY HOLD', tone: 'quarantine' },
    };
  }

  const qdr = last(events, 'QUALITY_DECISION_REQUIRED');
  if (qdr || result?.quality_decision_required) {
    return {
      visible: true,
      kind: 'quality_decision_required',
      headline: 'Quality decision required',
      tone: 'decision',
      lines: [str(qdr?.reason) || result?.reason || 'The evidence could not establish an answer.'],
      chip: { label: 'AWAITING QUALITY', tone: 'decision' },
    };
  }

  const computed = last(events, 'DISPOSITION_COMPUTED');
  const disposition = str(computed?.disposition) || result?.disposition || '';
  if (!disposition) return { visible: false, kind: 'released', headline: '', tone: 'progress', lines: [] };

  const consequence = consequenceFrom(events, result);
  const blocked = consequence?.readinessChanges.filter((c) => c.to === 'BLOCKED') ?? [];

  if (disposition === 'RELEASE') {
    return {
      visible: true,
      kind: 'released',
      headline: 'Released into usable inventory',
      tone: 'released',
      lines: [result?.reason || 'Every governing requirement was met by applicable evidence.'],
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
 * reviewer sees what was asserted and not merely its hash). The verifier's
 * COMPLETION EVENT carries only `brief_hash` — `agents.py` puts `sufficiency`
 * in the payload for the investigator alone — so the event stream cannot answer
 * this for the verifier and the stored record can.
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
  const qdr = last(events, 'QUALITY_DECISION_REQUIRED');
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

  const consequenceState: SpineNodeVM['state'] = consequence
    ? 'completed'
    : active === 'consequence'
      ? 'active'
      : 'pending';

  return [
    {
      key: 'evidence',
      label: 'Evidence',
      state: evidenceState,
      headline: halted ? 'Quarantined' : snapshot ? 'Frozen' : 'Arriving',
      note: halted
        ? 'withheld from the agents'
        : snapshot
          ? `${num(snapshot.claim_count) ?? 0} claims`
          : '',
    },
    {
      key: 'agents',
      label: 'Investigation & Verification',
      state: agentsState,
      headline: halted
        ? 'Never invoked'
        : reconciliation?.state === 'MATERIAL_DISAGREEMENT'
          ? 'Material disagreement'
          : verifier && investigator
            ? 'Independently reconciled'
            : 'Reasoning',
      note: investigator ? str(investigator.basis) : '',
      // Event payload first (it is live mid-run, before any record exists),
      // then the agent's own stored brief. Null until one of them answers —
      // the model documents these as null-until-known, never a placeholder.
      // On a disagreement the lane states what this agent SELECTED, because
      // that is what differs; otherwise it states sufficiency as before.
      investigatorLane:
        briefSelection(record, 'investigator', reconciliation) ||
        (investigator ? str(investigator.sufficiency) : '') ||
        briefSufficiency(record, 'investigator'),
      verifierLane:
        briefSelection(record, 'verifier', reconciliation) ||
        (verifier ? str(verifier.sufficiency) : '') ||
        briefSufficiency(record, 'verifier'),
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
        ? 'Withheld'
        : qdr
          ? 'Quality decision'
          : str(computed?.disposition) || 'Pending',
      note: computed ? str(computed.basis) : '',
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
  /**
   * The run has reached its authoritative end.
   *
   * Consequence is the LAST stage, so `index < activeIndex` can never collapse
   * it and the terminal frame kept it expanded — the full-bleed recovery grid,
   * the per-order readiness cards and the substitute reasoning, all competing
   * with the three questions the frame actually owes the operator. Once the
   * decision is final there is no live stage to watch, so it folds into the
   * reopenable stack with everything else.
   */
  terminal = false,
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
    const collapsed =
      STAGE_ORDER.indexOf(stageKey) < activeIndex || (terminal && stageKey === active);
    if (collapsed) out.push({ stageKey, title, oneLine, pill, runNumber });
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

const AGENT_LABEL: Record<string, string> = {
  INVESTIGATOR: 'Investigator',
  VERIFIER: 'Verifier',
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
      // The verb is "establish", never "release" or "approve": the human is
      // naming which measurement is controlling, and the engine still decides
      // what that means.
      actionLabel: equivalence
        ? `Establish ${str(o.method)} via ${equivalence}`
        : `Establish direct ${str(o.method)}`,
      // Stated, not implied. Where the two paths lead to different
      // dispositions, an operator choosing between two plausible numbers must
      // be told what each one leads to.
      consequence:
        o.within_limits === null || o.within_limits === undefined
          ? 'Consequence cannot be computed from this value'
          : passes
            ? `Deterministic evaluation will PASS${threshold ? ` — within ${threshold}` : ''}`
            : `Deterministic evaluation will FAIL${threshold ? ` — outside ${threshold}` : ''}`,
      passes,
    };
  });

  const characteristic = str(question.characteristic).replace(/_/g, ' ');
  const equivalenceId = str(question.equivalence_id);
  // The exact sentence. Every noun in it is a backend fact.
  // "Which", not "whether". The two paths lead to different dispositions, so
  // the operator is choosing between them rather than ratifying one.
  const question_text =
    `Which ${characteristic} determination should Quality establish as ` +
    `controlling for this decision?`;

  const position = (o: QualityAuthorityOptionVM | undefined): string =>
    o ? `Selected ${o.measurement}, ${o.basis}.` : '';

  return {
    questionId: str(question.question_id),
    question: question_text,
    characteristic: str(question.characteristic),
    equivalenceId,
    options,
    investigatorPosition: position(options.find((o) => o.selectedBy === 'INVESTIGATOR')),
    verifierPosition: position(options.find((o) => o.selectedBy === 'VERIFIER')),
    disputed: equivalenceId
      ? `${equivalenceId} · ${str(question.method_from)} → ${str(question.method_to)} at ${str(question.condition)}`
      : characteristic,
    // Deliberately NOT "Approve"/"Release". Establishing evidence names which
    // measurement is controlling; holding leaves the lot where it is. Neither
    // verb decides the lot.
    holdActionLabel: 'Keep held',
  };
}

/** §8. The durable stage that replaces the panel once a human has answered. */
export function qualityAuthorityFrom(
  authority: QualityAuthorityDTO | undefined,
): QualityAuthorityRecordVM | null {
  const decisions = authority?.decisions ?? [];
  if (decisions.length === 0) return null;
  const decision: HumanAuthorityDecisionDTO = decisions[decisions.length - 1];
  const authorized = str(decision.decision) === 'ESTABLISH_EVIDENCE';
  const characteristic = str(decision.characteristic).replace(/_/g, ' ');

  return {
    decision: authorized ? 'ESTABLISH_EVIDENCE' : 'KEEP_HELD',
    headline: authorized ? 'Controlling evidence established' : 'Kept held',
    tone: authorized ? 'released' : 'atrisk',
    question: qualityQuestionText(decision),
    // What was established, in the operator's own terms. The backend records
    // the measurement alongside the claim id precisely so this line does not
    // have to name an opaque reference months later.
    answer: authorized
      ? [
          [
            decision.established_value ?? '',
            str(decision.established_units),
          ]
            .filter(Boolean)
            .join(' '),
          str(decision.established_method),
          str(decision.established_condition),
        ]
          .filter(Boolean)
          .join(' · ')
          .concat(
            str(decision.established_via_equivalence)
              ? ` — via ${str(decision.established_via_equivalence)}`
              : ' — direct method',
          )
      : `Lot kept held; no ${characteristic} determination was established`,
    accountableActor: str(decision.accountable_actor),
    authoritySource: str(decision.authority_source),
    timestamp: str(decision.created_at),
    clock: clockOf(str(decision.created_at)),
    snapshotBinding: str(decision.claim_set_hash).slice(0, 12),
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

export function project(input: ProjectInput): DecisionWorkspaceVM {
  const events = [...input.events].sort(
    (a, b) => (num(a.sequence) ?? 0) - (num(b.sequence) ?? 0),
  );
  const result = input.result ?? null;
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
   */
  const terminal =
    active === 'consequence' &&
    Boolean(result) &&
    !input.running &&
    !disposition?.qualityDecisionRequired;
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
    activeStage: terminal ? null : active,
    // Still full-bleed at the terminal frame. The stage collapsed, but the
    // case-context column has nothing left to add once the decision is final,
    // and remounting it duplicated the lot identity the header already
    // carries. The frame keeps the full inner width.
    fullBleed: active ? FULL_BLEED.includes(active) : false,
    completed: completedFrom(
      events,
      active,
      { investigator, verifier, reconciliation, disposition, consequence },
      terminal,
    ),
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
    consequence,
    activity: toActivity(events).reverse(), // newest first (D7)
    failure,
    // One or the other, never both: an answered question has no panel, and an
    // unanswered one has no record. The control cannot outlive its decision.
    qualityAuthorityPanel: qualityPanelFrom(qualityAuthorityOf(input.record)),
    qualityAuthority: qualityAuthorityFrom(qualityAuthorityOf(input.record)),
  };
}
