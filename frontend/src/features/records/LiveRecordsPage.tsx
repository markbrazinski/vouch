/**
 * Records — durable proof of one decision, after the live run is gone.
 *
 * Everything rendered comes from the stored DecisionRecord. Where the record
 * holds nothing, this surface says so: an abstained run has no disposition, a
 * refused decision has no mutation, and neither is drawn as an empty panel that
 * looks like missing data.
 *
 * The human continuation is described as evidence supplied under a named
 * authority — never as "a human approved the AI". Vouch reassessed on the new
 * evidence and reached its own conclusion; the person supplied the document.
 */

import type { DecisionRecordVM, RunAgentVM, RunVM } from './model';
import { T } from '../../components/tokens';
import { StatusPill } from '../../components/StatusPill';
import { SurfaceState } from '../../components/SurfaceState';

const Label = ({ children }: { children: React.ReactNode }) => (
  <div style={{ font: "600 9.5px 'IBM Plex Mono'", letterSpacing: '.1em', color: T.faint }}>
    {children}
  </div>
);

function Panel({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      style={{
        background: T.panel,
        border: `1px solid ${T.hairline}`,
        borderRadius: 12,
        padding: '15px 18px',
      }}
    >
      <Label>{title}</Label>
      <div style={{ marginTop: 10 }}>{children}</div>
    </section>
  );
}

/** One agent's independent conclusion, from its own brief. */
function AgentColumn({ agent }: { agent: RunAgentVM | null }) {
  if (!agent) {
    return (
      <div style={{ font: "400 12px 'Public Sans'", color: T.faint }}>
        No brief recorded for this agent.
      </div>
    );
  }
  return (
    <div>
      <div style={{ font: "700 12px 'Public Sans'", color: T.ink, textTransform: 'capitalize' }}>
        {agent.role}
      </div>
      <div style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint, marginTop: 2 }}>
        {agent.modelId || '—'} · {agent.promptVersion || '—'}
      </div>
      {agent.governingBasis && (
        <div style={{ font: "400 11.5px 'Public Sans'", color: T.ink70, marginTop: 6 }}>
          Governing basis: <strong>{agent.governingBasis}</strong>
        </div>
      )}
      {agent.covered.length > 0 && (
        <div style={{ font: "400 11.5px 'Public Sans'", color: '#3E6B54', marginTop: 4 }}>
          Covered: {agent.covered.join(', ')}
        </div>
      )}
      {agent.missing.length > 0 && (
        <div style={{ font: "400 11.5px 'Public Sans'", color: '#8a6318', marginTop: 4 }}>
          Not established: {agent.missing.join(', ')}
        </div>
      )}
      <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint, marginTop: 6 }}>
        {agent.toolCount} authoritative {agent.toolCount === 1 ? 'lookup' : 'lookups'}
        {agent.briefHash && ` · brief ${agent.briefHash.slice(0, 12)}`}
      </div>
    </div>
  );
}

function RunBlock({ run, runCount }: { run: RunVM; runCount: number }) {
  return (
    <div
      data-testid={`record-run-${run.runNumber}`}
      data-run={run.runNumber}
      style={{
        border: `1px solid ${T.hairline}`,
        borderRadius: 11,
        padding: '14px 16px',
        background: '#FCFBF7',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ font: "700 12px 'IBM Plex Mono'", color: T.ink }}>
          RUN {run.runNumber}
          {runCount > 1 && <span style={{ color: T.faint }}> of {runCount}</span>}
        </span>
        {run.abstained ? (
          <StatusPill tone="decision" label="NO DISPOSITION REACHED" size="sm" />
        ) : (
          <StatusPill tone={run.tone} label={run.disposition} size="sm" />
        )}
        <StatusPill
          tone={run.reconciliation.agreed ? 'released' : 'atrisk'}
          label={run.reconciliation.outcome}
          size="sm"
        />
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 18,
          marginTop: 12,
          paddingTop: 12,
          borderTop: `1px solid ${T.hairline}`,
        }}
      >
        <AgentColumn agent={run.investigator} />
        <AgentColumn agent={run.verifier} />
      </div>

      {run.reconciliation.differingFields.length > 0 && (
        <div style={{ font: "400 11.5px 'Public Sans'", color: '#8a6318', marginTop: 10 }}>
          The two agents differed on:{' '}
          <strong>{run.reconciliation.differingFields.join(', ')}</strong>. A material
          disagreement blocks a mutation and routes the case to Quality.
        </div>
      )}

      {run.dispositionReason && (
        <div style={{ font: "400 12px/1.55 'Public Sans'", color: T.ink70, marginTop: 10 }}>
          {run.dispositionReason}
        </div>
      )}

      {/* An abstention is an outcome, not an error. Say what it means. */}
      {run.abstained && (
        <div style={{ font: "400 12px/1.55 'Public Sans'", color: T.muted, marginTop: 8 }}>
          This run reached no disposition. The evidence could not establish the answer, so
          nothing was released and nothing was marked defective.
        </div>
      )}
    </div>
  );
}

export function LiveRecordsPage({
  vm,
  onOpenSource,
}: {
  vm: DecisionRecordVM;
  onOpenSource?: (artifactId: string) => void;
}) {
  return (
    <div
      data-testid="records-page"
      data-record={vm.recordId}
      style={{ padding: '20px 30px 60px', maxWidth: 1180, margin: '0 auto' }}
    >
      <Label>DECISION RECORD</Label>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          marginTop: 6,
          flexWrap: 'wrap',
        }}
      >
        <h2
          style={{
            margin: 0,
            font: "800 23px 'Public Sans'",
            letterSpacing: '-.02em',
            color: T.ink,
          }}
        >
          {vm.lotId || vm.recordId}
        </h2>
        {vm.securityBlocked ? (
          <StatusPill tone="refused" label="SECURITY HOLD" />
        ) : vm.qualityDecisionRequired ? (
          <StatusPill tone="decision" label="QUALITY DECISION REQUIRED" />
        ) : (
          <StatusPill tone={vm.tone} label={vm.disposition || 'NO DISPOSITION'} />
        )}
        {vm.runCount > 1 && (
          <StatusPill tone="progress" label={`${vm.runCount} RUNS · ONE RECORD`} size="sm" />
        )}
      </div>
      <div style={{ font: "400 11.5px 'IBM Plex Mono'", color: T.faint, marginTop: 6 }}>
        {vm.recordId}
        {vm.materialId && ` · ${vm.materialId}`}
        {vm.supplierId && ` · ${vm.supplierId}`}
        {vm.supplierSite && ` · site ${vm.supplierSite}`}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 18 }}>
        {/* --- evidence -------------------------------------------------- */}
        <Panel title="EVIDENCE" testId="record-evidence">
          {vm.evidence.length === 0 ? (
            <SurfaceState
              kind="empty"
              headline="No evidence artifact is recorded on this decision."
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
              {vm.evidence.map((e) => (
                <div
                  key={e.artifactId}
                  data-artifact={e.artifactId}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    flexWrap: 'wrap',
                    padding: '9px 12px',
                    background: e.excluded ? '#F6EEE6' : '#FCFBF7',
                    border: `1px solid ${e.excluded ? 'rgba(154,90,42,.36)' : T.hairline}`,
                    borderRadius: 9,
                  }}
                >
                  <span style={{ font: "700 11.5px 'IBM Plex Mono'", color: T.ink }}>
                    {e.documentIdentity || 'DOCUMENT'}
                  </span>
                  <StatusPill
                    tone={e.humanAuthorized ? 'released' : 'progress'}
                    label={e.trustLabel}
                    size="sm"
                  />
                  {e.excluded && <StatusPill tone="refused" label="EXCLUDED FROM USE" size="sm" />}
                  <span style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint }}>
                    {e.claimCount} {e.claimCount === 1 ? 'claim' : 'claims'}
                    {e.contentHash && ` · ${e.contentHash.slice(0, 12)}`}
                    {e.objectVersion && ` · v${e.objectVersion.slice(0, 8)}`}
                  </span>
                  {onOpenSource && (
                    <button
                      onClick={() => onOpenSource(e.artifactId)}
                      style={{
                        marginLeft: 'auto',
                        padding: '5px 11px',
                        background: 'transparent',
                        border: '1px solid rgba(0,0,0,.18)',
                        borderRadius: 7,
                        font: "600 11px 'Public Sans'",
                        color: T.ink70,
                        cursor: 'pointer',
                      }}
                    >
                      Open source →
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* --- runs ------------------------------------------------------ */}
        <Panel title={vm.runs.length > 1 ? 'RUNS · SAME RECORD' : 'RUN'} testId="record-runs">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
            {vm.runs.map((run) => (
              <RunBlock key={run.runNumber} run={run} runCount={vm.runCount} />
            ))}
          </div>
        </Panel>

        {/* --- human continuation ---------------------------------------- */}
        {vm.human.occurred && (
          <Panel title="HUMAN EVIDENCE" testId="record-human">
            <div style={{ font: "400 12.5px/1.6 'Public Sans'", color: T.ink70 }}>
              Authoritative evidence was supplied under{' '}
              <strong>{vm.human.authoritySource || 'a named authority'}</strong>, and the same
              decision record resumed. Vouch reassessed on the new evidence and reached its own
              conclusion — this is not an approval of an earlier answer.
            </div>
            <div style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint, marginTop: 7 }}>
              {vm.human.evidenceSupplied.length}{' '}
              {vm.human.evidenceSupplied.length === 1 ? 'artifact' : 'artifacts'}
              {vm.human.resumedRunIds.length > 0 &&
                ` · resumed ${vm.human.resumedRunIds.join(', ')}`}
            </div>
          </Panel>
        )}

        {/* --- authority / mutation -------------------------------------- */}
        <Panel title="AUTHORITY AND STATE CHANGE" testId="record-mutation">
          {vm.mutation.occurred ? (
            <div>
              <div style={{ font: "600 12.5px 'Public Sans'", color: T.ink }}>
                {vm.mutation.result}
              </div>
              <div style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint, marginTop: 5 }}>
                {vm.mutation.action} · {vm.mutation.targetType} {vm.mutation.targetId}
                {vm.mutation.versionChange && ` · ${vm.mutation.versionChange}`}
              </div>
              {vm.mutation.ledgerSequence && (
                <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint, marginTop: 3 }}>
                  {vm.mutation.ledgerSequence}
                </div>
              )}
            </div>
          ) : (
            /* Nothing changed. Said plainly — this is the fail-safe working. */
            <div style={{ font: "400 12.5px/1.6 'Public Sans'", color: T.muted }}>
              <strong style={{ color: T.ink }}>No state change.</strong>{' '}
              {vm.securityBlocked
                ? 'The evidence was quarantined before any agent ran, so nothing was authorized.'
                : 'No mutation was authorized for this decision, so no lot or order state was altered.'}
            </div>
          )}
        </Panel>

        {/* --- consequence ----------------------------------------------- */}
        {(vm.consequence.readinessChanges.length > 0 ||
          vm.consequence.recoveryCandidates.length > 0) && (
          <Panel title="OPERATIONAL CONSEQUENCE" testId="record-consequence">
            {vm.consequence.readinessChanges.map((c) => (
              <div key={c.orderId} style={{ marginBottom: 8 }}>
                <span style={{ font: "700 12px 'IBM Plex Mono'", color: T.ink }}>{c.orderId}</span>
                <span style={{ font: "400 12px 'Public Sans'", color: T.muted }}>
                  {' '}
                  {c.from} → <strong style={{ color: '#8E2B24' }}>{c.to}</strong>
                  {c.reason && ` · ${c.reason}`}
                </span>
              </div>
            ))}
            {vm.consequence.recoveryCandidates.length > 0 && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${T.hairline}` }}>
                <Label>RECOVERY EVALUATED</Label>
                <div style={{ marginTop: 7, display: 'flex', flexDirection: 'column', gap: 5 }}>
                  {vm.consequence.recoveryCandidates.map((c) => (
                    <div
                      key={`${c.kind}-${c.candidateId}`}
                      style={{ font: "400 11.5px 'IBM Plex Mono'", color: T.ink70 }}
                    >
                      {c.kind} · {c.candidateId} —{' '}
                      <strong
                        style={{
                          color:
                            c.verdict === 'ELIGIBLE'
                              ? '#3E6B54'
                              : c.verdict === 'REFUSED'
                                ? '#4A2018'
                                : '#8a6318',
                        }}
                      >
                        {c.verdict}
                      </strong>
                      {c.reasonCode && ` (${c.reasonCode})`}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>
        )}

        {vm.auditHash && (
          <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint }}>
            audit hash {vm.auditHash.slice(0, 24)}
          </div>
        )}
      </div>
    </div>
  );
}
