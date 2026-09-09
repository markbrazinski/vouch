import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(import.meta.dirname, '..');

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__') continue;
      sourceFiles(p, acc);
    } else if (/\.tsx?$/.test(name)) {
      acc.push(p);
    }
  }
  return acc;
}

/** Everything shipped to a judge, i.e. every source file that is not the dev harness. */
const productFiles = sourceFiles(SRC).filter((p) => !p.includes(`${join('src', 'dev')}`));

describe('the product surface carries no demo apparatus', () => {
  it('no page fetches or invents a backend route', () => {
    // `adapter/client.ts` is the ONE sanctioned transport seam. It exists so no
    // component has to reach for the network itself; keeping the ban on every
    // other file is what makes that true rather than aspirational.
    const CLIENT = join('src', 'adapter', 'client.ts');
    for (const f of productFiles.filter((p) => !p.endsWith(CLIENT))) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/\bfetch\s*\(/);
      expect(src, f).not.toMatch(/XMLHttpRequest|EventSource|new WebSocket/);
    }
  });

  it('the transport seam reaches only the same-origin BFF', () => {
    const src = readFileSync(join(SRC, 'adapter', 'client.ts'), 'utf8');
    // No absolute origin: an absolute URL would be a second backend, and a
    // cross-origin one would need credentials the browser must never hold.
    expect(src).not.toMatch(/https?:\/\//);
    expect(src).not.toMatch(/amazonaws\.com|bedrock-agentcore/);
    expect(src).toMatch(/'\/api'/);
  });

  it('no fake timer manufactures product state', () => {
    // The rule is about AUTHORSHIP, not about the API. A timer that decides
    // what happened next is demo apparatus; a timer that asks the server what
    // happened is a poll, and polling is how the live event path works at all.
    //
    // So exactly one file may hold an interval — the decision run — and it is
    // separately constrained below to prove the interval only fetches.
    const POLLER = join('src', 'decision', 'useDecisionRun.ts');
    for (const f of productFiles.filter((p) => !p.endsWith(POLLER))) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/setTimeout|setInterval/);
    }
  });

  it('the one permitted interval only polls the backend', () => {
    const src = readFileSync(join(SRC, 'decision', 'useDecisionRun.ts'), 'utf8');

    // Exactly one interval, and it only ever drives the watcher.
    //
    // The tick used to call `pollOnce` directly. It now calls `tick`, which
    // polls events AND asks the backend whether the decision is terminal —
    // both are reads. What matters is unchanged and is asserted below: the
    // timer fetches, and authors nothing.
    const intervals = src.match(/setInterval\(/g) ?? [];
    expect(intervals).toHaveLength(1);
    expect(src).toMatch(/setInterval\(\(\) => void tick\(\), POLL_MS\)/);

    // It is always cleared: an orphaned poll would keep asking about a decision
    // nobody is watching.
    expect(src).toMatch(/clearInterval/);

    // And the timer never decides anything. No lifecycle vocabulary, no stage
    // names and no dispositions are authored on a tick.
    const tick = src.slice(src.indexOf('const pollOnce'), src.indexOf('const start'));
    expect(tick).not.toMatch(/DISPOSITION|QUARANTINE|RELEASE|INVESTIGATOR_STARTED/);

    // Whether the run stopped is READ from the record, never inferred from
    // which events happened to arrive. Inferring it would put "which event ends
    // this path" — domain logic — into the client.
    expect(src).toMatch(/document\.terminal === true/);
    expect(src).toMatch(/review_status === 'OPEN'/);
    // The terminal check is throttled, not driven by a second timer.
    expect(src).toMatch(/TERMINAL_CHECK_TICKS/);
  });

  it('the client owns a decision id before any decision runs', () => {
    // Without this the live path is impossible: a caller that learns the id
    // from the response can only ever poll a decision that already finished.
    const src = readFileSync(join(SRC, 'decision', 'useDecisionRun.ts'), 'utf8');
    expect(src).toMatch(/newDecisionRecordId\(\)/);
    expect(src).toMatch(/decisionRecordId: recordId/);
  });

  it('no hard-coded hero outcome ships in the product surface', () => {
    // The entry names a LOT and carries the supplier's own document. It must
    // never name what Vouch will conclude — that comes from the backend.
    const DTO = join('src', 'decision', 'dto.ts');
    const MODEL = join('src', 'decision', 'model.ts');
    const ADAPTER = join('src', 'decision', 'adapter.ts');
    const SPINE = join('src', 'decision', 'DecisionSpine.tsx');
    const WORKSPACE = join('src', 'decision', 'DecisionWorkspace.tsx');
    const STAGES = join('src', 'decision', 'Stages.tsx');
    const VIEWER = join('src', 'decision', 'SourceDocumentViewer.tsx');
    const CONTEXT = join('src', 'decision', 'CaseContextColumn.tsx');
    // These legitimately name dispositions: they are the type space and the
    // presentation rules for whatever the backend returns.
    const typeSpace = [DTO, MODEL, ADAPTER, SPINE, WORKSPACE, STAGES, VIEWER, CONTEXT];

    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    expect(main).not.toMatch(/QUARANTINE|RELEASE|INSUFFICIENT_EVIDENCE/);
    expect(main).not.toMatch(/BLOCKED|C-417|C-418/);

    // Scoped to the Hero A surface. The older fixture-driven screens carry
    // their own demo data and are out of this gate's scope; what must be true
    // is that nothing on the LIVE path presumes an outcome.
    const heroSurface = productFiles.filter(
      (p) => p.includes(join('src', 'decision')) && !typeSpace.some((t) => p.endsWith(t)),
    );
    expect(heroSurface.length).toBeGreaterThan(0);
    for (const f of heroSurface) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/SPEC-A7/);
    }
  });

  it('a presigned source reference is never persisted', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      // Nothing anywhere WRITES to persistent storage. A view ref could only
      // leak through a write, and banning writes outright is stronger than
      // trying to prove a particular value never reaches one.
      expect(src, f).not.toMatch(/(localStorage|sessionStorage)\.setItem/);
      expect(src, f).not.toMatch(/document\.cookie\s*=/);
    }
    const viewer = readFileSync(join(SRC, 'decision', 'SourceDocumentViewer.tsx'), 'utf8');
    // Held in a ref, never in state that a render tree would retain.
    expect(viewer).toMatch(/viewRef = useRef<string \| null>\(null\)/);
    // The presigned URL is never handed to a new tab or to the address bar.
    // The bytes are fetched and framed as a same-origin blob instead, so the
    // credential stays inside this document and out of browser history.
    expect(viewer).not.toMatch(/window\.open/);
    expect(viewer).toMatch(/fetchSourceObjectUrl/);
  });

  it('no design HTML or reference markup ships', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/Vouch_Journey|\.dc\.html|sc-if|x-dc/);
    }
  });

  it('no AWS SDK or credential reaches the browser', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/from ['"]@?aws-sdk/);
      expect(src, f).not.toMatch(/AccessKeyId|SecretAccessKey|X-Amz-Signature/);
      expect(src, f).not.toMatch(/AKIA[0-9A-Z]{16}/);
    }
  });

  it('no observability surface exists in the product UI', () => {
    // Sponsor-depth §7: observability is engineering proof, never product UI.
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/CloudWatch|X-Ray|OpenTelemetry|OTEL_|trace[_ ]?id/i);
      expect(src, f).not.toMatch(/AgentCore|Bedrock|Textract|Amazon/i);
    }
  });

  it('no prototype bar, judge control, or AI activity feed in product chrome', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/PROTOTYPE STATES|Cleared by Vouch|no run lost|thought feed/i);
    }
  });

  /**
   * The LIVE product surfaces.
   *
   * `src/features/*` still contains the earlier fixture-driven screens
   * (`IncomingPage`, `SuppliersPage`, `TodayPage`, `RecordsPage`). They are
   * reachable only from `VouchApp`, which `main.tsx` does not mount — they back
   * the DEV state harness and its tests. The rules below therefore bind the
   * surfaces that actually ship: the `Live*Page` components, their models, and
   * the bindings in `Surfaces.tsx`.
   */
  const liveSurfaces = productFiles.filter(
    (p) =>
      p.includes(join('src', 'features')) &&
      (/Live[A-Za-z]+Page\.tsx$/.test(p) ||
        /features[\\/][a-z]+[\\/]model\.ts$/.test(p) ||
        p.endsWith(join('src', 'features', 'Surfaces.tsx')) ||
        p.endsWith(join('src', 'features', 'useSurfaceData.ts'))),
  );

  /** Comments explain WHY a rule exists; only executable code can break it. */
  const codeOf = (file: string) =>
    readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:])\/\/.*$/gm, '$1');

  it('the live surfaces do no domain arithmetic', () => {
    // Readiness, coverage, shortage and every ratio are deterministic Python
    // (AGENTS.md §6). A browser that recomputed one could disagree with the
    // decision that produced it, so the surfaces format and never derive.
    expect(liveSurfaces.length).toBeGreaterThan(0);
    for (const f of liveSurfaces) {
      const src = codeOf(f);
      // Subtraction or division on a coverage figure is where a re-derived
      // shortage or ratio would appear. Counting array lengths is inventory,
      // not domain arithmetic, so `.length` and `+= 1` stay allowed.
      expect(src, f).not.toMatch(/required\s*[-/]\s*available/);
      expect(src, f).not.toMatch(/available\s*[-/]\s*required/);
      expect(src, f).not.toMatch(/(shortBy|short_by|ratio|coverage)\s*[:=]\s*[^,;]*[-*/]\s*[a-z]/i);
    }
  });

  it('no live surface resurrects the rejected fictional counters', () => {
    // `inProgress` and `completedByVouch` were rejected: invocation is
    // synchronous so nothing is ever persisted mid-flight, and nothing in the
    // model attributes a decision to Vouch rather than to a human.
    for (const f of liveSurfaces) {
      const src = codeOf(f);
      expect(src, f).not.toMatch(/completedByVouch|completed_by_vouch/);
      expect(src, f).not.toMatch(/inProgress|in_progress/);
    }
  });

  it('no live surface invents supplier standing the backend does not own', () => {
    // Qualification status, dates and site scope are read by an agent tool but
    // never serialized into a browser-reachable response, and a supplier score
    // or risk model exists nowhere in the backend at all.
    const suppliers = liveSurfaces.filter((p) => p.includes(join('features', 'suppliers')));
    expect(suppliers.length).toBeGreaterThan(0);
    for (const f of suppliers) {
      const src = codeOf(f);
      expect(src, f).not.toMatch(/REQUAL|riskScore|supplierScore|trendline|qualificationStatus/);
    }
  });

  it('no live surface hard-codes a demo lot, order or spec', () => {
    // `LiveTodayPage` must not know C-417 exists; it renders whatever the
    // backend returned.
    for (const f of liveSurfaces) {
      const src = codeOf(f);
      expect(src, f).not.toMatch(/C-41[789]|LOT-100\d|SPEC-A7|MAT-ALLOY-7|L-22\d\d/);
      expect(src, f).not.toMatch(/Meridian|Halden|Kessler|Baumann|Orica/);
    }
  });

  it('no invented total or count ships on a live surface', () => {
    // "1-10 of 3,481" and "5 of 214" asserted totals nothing ever counted.
    for (const f of liveSurfaces) {
      const src = codeOf(f);
      expect(src, f).not.toMatch(/3,481|of 214|\b187\b|\b3481\b/);
    }
  });

  it('references only the CANONICAL qualified supplier PDF', () => {
    // This guard originally banned every PDF reference, because the synthetic
    // supplier documents did not exist yet. They exist now, are hash-frozen in
    // demo/evidence/MANIFEST.md and are qualified by
    // tests/v2/test_canonical_pdf_assets.py, so the rule becomes the stricter
    // one it was always standing in for: the product may reference the
    // canonical assets and nothing else. An ad-hoc or generated PDF still fails.
    // All four canonical arrivals, one per lot Incoming lists. Named
    // exhaustively rather than pattern-matched on a directory, so adding a
    // fifth document is a deliberate edit here and not an accident.
    const CANONICAL =
      /(northern-alloys-coa-lot-1001|eastern-metals-coa-lot-1002|northern-alloys-mtr-lot-1003|central-forgeworks-coa-lot-1004)\.pdf/;
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      for (const match of src.match(/[\w./-]+\.pdf/g) ?? []) {
        expect(match, `${f} references a non-canonical PDF`).toMatch(CANONICAL);
      }
    }
  });

  it('the fixture harness is imported only behind import.meta.env.DEV', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    expect(main).toMatch(/import\.meta\.env\.DEV/);
    // The only reference to the harness module is the dynamic, dev-guarded import.
    const refs = productFiles.filter((f) => /VouchStateHarness/.test(readFileSync(f, 'utf8')));
    expect(refs.map((f) => f.replace(SRC, ''))).toEqual([join('/', 'main.tsx')]);
  });
});
