import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import "./styles.css";

type CaseStatus =
  | "received"
  | "gathering_facts"
  | "ready_for_policy"
  | "awaiting_decision"
  | "authorized"
  | "executing"
  | "verifying"
  | "reconciling"
  | "reopen_required"
  | "waiting"
  | "completed"
  | "cancelled"
  | "failed";

type QueueItem = {
  case_id: string;
  case_kind: string;
  status: CaseStatus;
  subject_ref: string;
  requester_principal_id: string;
  version: number;
  authority_epoch: number;
  updated_at: string;
};

type CaseDetail = {
  case: Record<string, unknown>;
  policy: Record<string, unknown> | null;
  governance: Record<string, unknown> | null;
  obligations: Record<string, unknown> | null;
  evidence_links?: Array<Record<string, unknown>>;
  qualification_assessments?: Array<Record<string, unknown>>;
  effects: Array<Record<string, unknown>>;
  outcomes: Array<Record<string, unknown>>;
  audit: Array<Record<string, unknown>> | null;
};

type IntakeDisposition =
  | "admit"
  | "needs_clarification"
  | "information_only"
  | "unsupported"
  | "duplicate"
  | "ambiguous"
  | "requires_human_review";

type CandidateStatus = "active" | "superseded" | "admitted" | "rejected";

type IntakeAssessment = {
  assessment_id: string;
  candidate_ref: string;
  disposition: IntakeDisposition;
  basis: Record<string, unknown>;
  authority: "model_suggestion" | "deterministic_rule" | "human_review";
  is_final: boolean;
  reviewer_principal_id: string | null;
  created_at: string;
};

type IntakeQueueItem = {
  candidate_id: string;
  conversation_ref: string;
  candidate_requester: string;
  candidate_intent: string;
  status: CandidateStatus;
  created_at: string;
  latest_assessment: IntakeAssessment | null;
};

type IntakeCandidateDetail = {
  candidate: {
    candidate_id: string;
    conversation_ref: string;
    interpretation_refs: string[];
    candidate_requester: string;
    candidate_intent: string;
    candidate_fact_refs: string[];
    source_refs: string[];
    created_at: string;
    supersedes_candidate_ref: string | null;
    status: CandidateStatus;
  };
  assessments: IntakeAssessment[];
  promotion: Record<string, unknown> | null;
};

type CommitmentCandidate = {
  candidate_commitment_id: string;
  source_artifact_ref: string;
  interpretation_ref: string;
  evidence_span_refs: string[];
  candidate_committer_identity: string;
  candidate_action: string;
  candidate_due_text: string | null;
  candidate_due_at: string | null;
  candidate_scope_ref: string | null;
  candidate_beneficiary: string | null;
  classification: string;
  status: string;
  created_at: string;
};

type CommitmentQueueItem = {
  candidate: CommitmentCandidate;
  resolution: Record<string, unknown> | null;
  commitment: Record<string, unknown> | null;
};

type CommitmentDetail = CommitmentQueueItem;

type ConsoleView = "cases" | "intake" | "commitments";

const config = {
  apiBase: import.meta.env.VITE_OPERATIONS_API_BASE_URL || "http://127.0.0.1:8001",
  oidcAuthority: import.meta.env.VITE_OIDC_AUTHORITY || "",
  oidcClientId: import.meta.env.VITE_OIDC_CLIENT_ID || "",
  oidcScope: import.meta.env.VITE_OIDC_SCOPE || "openid",
};

const root = document.querySelector<HTMLDivElement>("#app")!;
if (!root) throw new Error("#app is required");

const userManager =
  config.oidcAuthority && config.oidcClientId
    ? new UserManager({
        authority: config.oidcAuthority,
        client_id: config.oidcClientId,
        redirect_uri: `${window.location.origin}${window.location.pathname}`,
        post_logout_redirect_uri: `${window.location.origin}${window.location.pathname}`,
        response_type: "code",
        scope: config.oidcScope,
        userStore: new WebStorageStateStore({ store: window.sessionStorage }),
        stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
        automaticSilentRenew: false,
      })
    : null;

let currentUser: User | null = null;
let queue: QueueItem[] = [];
let selected: CaseDetail | null = null;
let selectedId: string | null = null;
let intakeQueue: IntakeQueueItem[] = [];
let selectedCandidate: IntakeCandidateDetail | null = null;
let selectedCandidateId: string | null = null;
let commitmentQueue: CommitmentQueueItem[] = [];
let selectedCommitment: CommitmentDetail | null = null;
let selectedCommitmentId: string | null = null;
let activeView: ConsoleView = "intake";
let errorMessage = "";
let busy = false;

async function init(): Promise<void> {
  if (userManager && window.location.search.includes("code=")) {
    currentUser = await userManager.signinRedirectCallback();
    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (userManager) {
    currentUser = await userManager.getUser();
  }
  render();
  if (currentUser && !currentUser.expired) {
    await Promise.all([loadQueue(), loadIntakeQueue(), loadCommitmentQueue()]);
  }
}

function token(): string {
  if (!currentUser || currentUser.expired || !currentUser.access_token) {
    throw new Error("OIDC session is not authenticated");
  }
  return currentUser.access_token;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token()}`);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${config.apiBase}${path}`, { ...init, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}${text ? `: ${text}` : ""}`);
  }
  return (await response.json()) as T;
}

async function loadQueue(): Promise<void> {
  busy = true;
  errorMessage = "";
  render();
  try {
    queue = await api<QueueItem[]>(
      "/v1/operations/cases?status=reconciling&status=reopen_required&status=waiting&status=failed&limit=500",
    );
    if (selectedId && queue.some((item) => item.case_id === selectedId)) {
      selected = await api<CaseDetail>(`/v1/operations/cases/${selectedId}`);
    }
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function selectCase(caseId: string): Promise<void> {
  busy = true;
  errorMessage = "";
  selectedId = caseId;
  render();
  try {
    selected = await api<CaseDetail>(`/v1/operations/cases/${caseId}`);
  } catch (error) {
    selected = null;
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function appendQualificationAssessment(): Promise<void> {
  if (!selectedId || !selected) return;
  const assessmentKind = root.querySelector<HTMLSelectElement>("#qualification-kind")?.value;
  const ruleRef = root.querySelector<HTMLInputElement>("#qualification-rule")?.value.trim();
  const inputRefs = (root.querySelector<HTMLInputElement>("#qualification-inputs")?.value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  const result = root.querySelector<HTMLSelectElement>("#qualification-result")?.value;
  if (!assessmentKind || !ruleRef || inputRefs.length === 0 || !result) {
    errorMessage = "Qualification kind, rule, input references, and result are required.";
    render();
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api(`/v1/operations/cases/${selectedId}/qualification-assessments`, {
      method: "POST",
      body: JSON.stringify({
        assessment_kind: assessmentKind,
        input_refs: inputRefs,
        rule_ref: ruleRef,
        result,
        blocking_reasons: [],
      }),
    });
    selected = await api<CaseDetail>(`/v1/operations/cases/${selectedId}`);
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function loadIntakeQueue(): Promise<void> {
  busy = true;
  errorMessage = "";
  render();
  try {
    intakeQueue = await api<IntakeQueueItem[]>(
      "/v1/operations/intake/candidates?status=active&limit=500",
    );
    if (selectedCandidateId && intakeQueue.some((item) => item.candidate_id === selectedCandidateId)) {
      selectedCandidate = await api<IntakeCandidateDetail>(
        `/v1/operations/intake/candidates/${selectedCandidateId}`,
      );
    }
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function selectCandidate(candidateId: string): Promise<void> {
  busy = true;
  errorMessage = "";
  selectedCandidateId = candidateId;
  render();
  try {
    selectedCandidate = await api<IntakeCandidateDetail>(
      `/v1/operations/intake/candidates/${candidateId}`,
    );
  } catch (error) {
    selectedCandidate = null;
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function loadCommitmentQueue(): Promise<void> {
  busy = true;
  errorMessage = "";
  render();
  try {
    commitmentQueue = await api<CommitmentQueueItem[]>(
      "/v1/operations/commitments/candidates?status=active&limit=500",
    );
    if (
      selectedCommitmentId &&
      commitmentQueue.some((item) => item.candidate.candidate_commitment_id === selectedCommitmentId)
    ) {
      selectedCommitment = await api<CommitmentDetail>(
        `/v1/operations/commitments/candidates/${selectedCommitmentId}`,
      );
    }
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function selectCommitment(candidateId: string): Promise<void> {
  busy = true;
  errorMessage = "";
  selectedCommitmentId = candidateId;
  render();
  try {
    selectedCommitment = await api<CommitmentDetail>(
      `/v1/operations/commitments/candidates/${candidateId}`,
    );
  } catch (error) {
    selectedCommitment = null;
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function resolveCommitmentSpeaker(): Promise<void> {
  if (!selectedCommitmentId) return;
  const externalSubject = root
    .querySelector<HTMLInputElement>("#commitment-external-subject")
    ?.value.trim();
  const basisInput = root.querySelector<HTMLTextAreaElement>("#commitment-basis")?.value.trim() || "";
  if (!externalSubject) {
    errorMessage = "A verified Feishu external subject is required.";
    render();
    return;
  }
  let basis: Record<string, unknown> = {};
  try {
    basis = basisInput ? (JSON.parse(basisInput) as Record<string, unknown>) : { reviewed: true };
  } catch {
    errorMessage = "Speaker resolution basis must be valid JSON.";
    render();
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api(`/v1/operations/commitments/candidates/${selectedCommitmentId}/resolve-speaker`, {
      method: "POST",
      body: JSON.stringify({ external_subject: externalSubject, provider: "feishu", basis }),
    });
    selectedCommitment = await api<CommitmentDetail>(
      `/v1/operations/commitments/candidates/${selectedCommitmentId}`,
    );
    await loadCommitmentQueue();
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function confirmCommitment(): Promise<void> {
  if (!selectedCommitmentId) return;
  const dueAt = root.querySelector<HTMLInputElement>("#commitment-due-at")?.value;
  const dueBasis = root.querySelector<HTMLInputElement>("#commitment-due-basis")?.value.trim();
  if (!dueAt || !dueBasis) {
    errorMessage = "Qualified due time and its basis are required.";
    render();
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api(`/v1/operations/commitments/candidates/${selectedCommitmentId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ qualified_due_at: new Date(dueAt).toISOString(), due_time_basis: dueBasis }),
    });
    await loadCommitmentQueue();
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function finalizeIntakeAssessment(): Promise<void> {
  if (!selectedCandidateId) return;
  const disposition = root.querySelector<HTMLSelectElement>("#intake-disposition")?.value as
    | IntakeDisposition
    | undefined;
  const basisInput = root.querySelector<HTMLTextAreaElement>("#intake-basis")?.value.trim() || "";
  if (!disposition) return;
  let basis: Record<string, unknown> = {};
  if (basisInput) {
    try {
      basis = JSON.parse(basisInput) as Record<string, unknown>;
    } catch {
      errorMessage = "Review basis must be valid JSON.";
      render();
      return;
    }
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api<IntakeAssessment>(
      `/v1/operations/intake/candidates/${selectedCandidateId}/assessments`,
      {
        method: "POST",
        body: JSON.stringify({ disposition, basis }),
      },
    );
    selectedCandidate = await api<IntakeCandidateDetail>(
      `/v1/operations/intake/candidates/${selectedCandidateId}`,
    );
    await loadIntakeQueue();
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function promoteIntakeCandidate(): Promise<void> {
  if (!selectedCandidateId || !selectedCandidate) return;
  const assessment = selectedCandidate.assessments.find(
    (item) => item.is_final && item.disposition === "admit",
  );
  if (!assessment) {
    errorMessage = "A final human ADMIT assessment is required before promotion.";
    render();
    return;
  }
  const value = (id: string): string =>
    root.querySelector<HTMLInputElement>(`#${id}`)?.value.trim() || "";
  const payload = {
    assessment_id: assessment.assessment_id,
    source_system: value("intake-source-system"),
    tenant_ref: value("intake-tenant-ref"),
    source_event_id: value("intake-source-event"),
    requester_principal_id: value("intake-requester"),
    case_kind: value("intake-case-kind") || "intake",
    subject_ref: value("intake-subject") || null,
    bridge_to_m5: ["employee-onboarding", "employee-offboarding"].includes(
      value("intake-case-kind"),
    ),
    bridge_to_m8: [
      "procurement-request",
      "invoice-ap-preparation",
      "expense-reimbursement",
    ].includes(value("intake-case-kind")),
    promotion_policy_ref:
      ["procurement-request", "invoice-ap-preparation", "expense-reimbursement"].includes(
        value("intake-case-kind"),
      )
        ? "m8-human-confirmed-v1"
        : value("intake-case-kind") === "employee-offboarding"
        ? "m7-human-confirmed-v1"
        : "m6-human-confirmed-v1",
  };
  if (!payload.source_system || !payload.tenant_ref || !payload.source_event_id || !payload.requester_principal_id) {
    errorMessage = "Source system, tenant, source event, and requester principal are required.";
    render();
    return;
  }
  if (!window.confirm("Create the existing Administrative request and case from this reviewed candidate?")) {
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    const result = await api<{ case: Record<string, unknown> }>(
      `/v1/operations/intake/candidates/${selectedCandidateId}/promote`,
      { method: "POST", body: JSON.stringify(payload) },
    );
    selectedId = String(result.case.case_id);
    activeView = "cases";
    selectedCandidate = null;
    selectedCandidateId = null;
    await loadQueue();
    if (selectedId) await selectCase(selectedId);
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

function switchView(view: ConsoleView): void {
  activeView = view;
  errorMessage = "";
  render();
}

async function refreshAuthoritativeFacts(): Promise<void> {
  if (!selectedId) return;
  if (!window.confirm("Refresh current authoritative HRIS facts and force policy/governance re-evaluation?")) {
    return;
  }
  busy = true;
  errorMessage = "";
  render();
  try {
    await api(`/v1/operations/cases/${selectedId}/authoritative-facts/refresh`, {
      method: "POST",
    });
    selected = await api<CaseDetail>(`/v1/operations/cases/${selectedId}`);
    await loadQueue();
  } catch (error) {
    errorMessage = error instanceof Error ? error.message : String(error);
  } finally {
    busy = false;
    render();
  }
}

async function login(): Promise<void> {
  if (!userManager) {
    errorMessage = "OIDC console configuration is missing.";
    render();
    return;
  }
  await userManager.signinRedirect();
}

async function logout(): Promise<void> {
  if (!userManager) return;
  await userManager.signoutRedirect();
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pretty(value: unknown): string {
  return escapeHtml(JSON.stringify(value, null, 2));
}

function statusClass(status: CaseStatus): string {
  if (status === "failed" || status === "reopen_required") return "danger";
  if (status === "reconciling" || status === "waiting") return "warn";
  if (status === "completed") return "ok";
  return "neutral";
}

function intakeStatusClass(status: CandidateStatus): string {
  if (status === "superseded" || status === "rejected") return "danger";
  if (status === "admitted") return "ok";
  return "warn";
}

function renderCaseQueue(): string {
  return `
    <div class="panel-heading">
      <div>
        <h2>Exception queue</h2>
        <p>WAIT / RECONCILE / REASSESS / HUMAN REVIEW only.</p>
      </div>
      <button id="refresh-cases" ${!busy ? "" : "disabled"}>Refresh</button>
    </div>
    <div class="queue">
      ${
        queue
          .map(
            (item) => `
              <button class="queue-item ${item.case_id === selectedId ? "selected" : ""}" data-case-id="${escapeHtml(item.case_id)}">
                <div class="queue-row"><strong>${escapeHtml(item.subject_ref)}</strong><span class="badge ${statusClass(item.status)}">${escapeHtml(item.status)}</span></div>
                <div class="muted">${escapeHtml(item.case_kind)} · epoch ${item.authority_epoch} · v${item.version}</div>
                <div class="muted">${escapeHtml(new Date(item.updated_at).toLocaleString())}</div>
              </button>`,
          )
          .join("") || `<div class="empty">No current exceptions.</div>`
      }
    </div>`;
}

function renderIntakeQueue(): string {
  return `
    <div class="panel-heading">
      <div>
        <h2>Intake review</h2>
        <p>Candidate-only state. Human review is required before admission.</p>
      </div>
      <button id="refresh-intake" ${!busy ? "" : "disabled"}>Refresh</button>
    </div>
    <div class="queue">
      ${
        intakeQueue
          .map(
            (item) => `
              <button class="queue-item ${item.candidate_id === selectedCandidateId ? "selected" : ""}" data-candidate-id="${escapeHtml(item.candidate_id)}">
                <div class="queue-row"><strong>${escapeHtml(item.candidate_intent)}</strong><span class="badge ${intakeStatusClass(item.status)}">${escapeHtml(item.status)}</span></div>
                <div class="muted">${escapeHtml(item.candidate_requester)} · ${escapeHtml(item.conversation_ref)}</div>
                <div class="muted">${escapeHtml(new Date(item.created_at).toLocaleString())}</div>
                ${item.latest_assessment ? `<div class="muted">latest: ${escapeHtml(item.latest_assessment.disposition)} · ${escapeHtml(item.latest_assessment.authority)}</div>` : `<div class="muted">not yet assessed</div>`}
              </button>`,
          )
          .join("") || `<div class="empty">No active intake candidates.</div>`
      }
    </div>`;
}

function renderIntakeDetail(detail: IntakeCandidateDetail): string {
  const candidate = detail.candidate;
  const finalAdmit = detail.assessments.some(
    (item) => item.is_final && item.disposition === "admit",
  );
  const basis = detail.assessments.at(-1)?.basis ?? { reviewed: true };
  return `
    <div class="detail-heading">
      <div>
        <div class="eyebrow">Candidate administrative request</div>
        <h2>${escapeHtml(candidate.candidate_intent)}</h2>
        <div class="muted">${escapeHtml(candidate.candidate_id)} · ${escapeHtml(candidate.conversation_ref)}</div>
      </div>
      <span class="badge ${intakeStatusClass(candidate.status)}">${escapeHtml(candidate.status)}</span>
    </div>
    <div class="cards">
      ${section("Candidate", candidate)}
      <article class="card">
        <h3>Human assessment</h3>
        <p class="muted">The reviewer identity is taken from the authenticated OIDC principal. Model suggestions cannot authorize promotion.</p>
        <label for="intake-disposition">Disposition</label>
        <select id="intake-disposition">
          ${(["admit", "needs_clarification", "information_only", "unsupported", "duplicate", "ambiguous", "requires_human_review"] as IntakeDisposition[])
            .map((item) => `<option value="${item}" ${item === (detail.assessments.at(-1)?.disposition ?? "admit") ? "selected" : ""}>${item}</option>`)
            .join("")}
        </select>
        <label for="intake-basis">Review basis (JSON)</label>
        <textarea id="intake-basis" rows="4">${escapeHtml(JSON.stringify(basis, null, 2))}</textarea>
        <button id="save-intake-assessment" ${busy ? "disabled" : ""}>Record final human assessment</button>
      </article>
      <article class="card">
        <h3>Admission</h3>
        <p class="muted">Promotion creates the existing Administrative request/case path exactly once. All source identity fields are explicit.</p>
        <div class="form-grid">
          ${inputField("intake-source-system", "Source system", "", "test-provider")}
          ${inputField("intake-tenant-ref", "Tenant", "", "provider-tenant")}
          ${inputField("intake-source-event", "Source event", "", "verified-event-id")}
          ${inputField("intake-requester", "Requester Principal", "", "person:requester")}
          ${inputField("intake-case-kind", "Case kind", "intake", "employee-onboarding")}
          ${inputField("intake-subject", "Subject ref", "", "employee:1")}
        </div>
        <button id="promote-intake-candidate" ${finalAdmit && !busy ? "" : "disabled"}>Promote human-confirmed candidate</button>
      </article>
      ${section("Assessment history", detail.assessments)}
      ${detail.promotion ? section("Promotion", detail.promotion) : ""}
    </div>`;
}

function renderCommitmentQueue(): string {
  return `
    <div class="panel-heading">
      <div>
        <h2>Meeting commitments</h2>
        <p>Candidate-only transcript output. Identity and due time require human qualification.</p>
      </div>
      <button id="refresh-commitments" ${!busy ? "" : "disabled"}>Refresh</button>
    </div>
    <div class="queue">
      ${
        commitmentQueue
          .map(
            (item) => `
              <button class="queue-item ${item.candidate.candidate_commitment_id === selectedCommitmentId ? "selected" : ""}" data-commitment-id="${escapeHtml(item.candidate.candidate_commitment_id)}">
                <div class="queue-row"><strong>${escapeHtml(item.candidate.candidate_action)}</strong><span class="badge warn">${escapeHtml(item.candidate.classification)}</span></div>
                <div class="muted">speaker: ${escapeHtml(item.candidate.candidate_committer_identity)} · ${escapeHtml(item.candidate.candidate_due_text || "due time unresolved")}</div>
                <div class="muted">${escapeHtml(new Date(item.candidate.created_at).toLocaleString())}</div>
              </button>`,
          )
          .join("") || `<div class="empty">No active meeting commitment candidates.</div>`
      }
    </div>`;
}

function renderCommitmentDetail(detail: CommitmentDetail): string {
  const candidate = detail.candidate;
  const resolved = Boolean(detail.resolution);
  const admitted = Boolean(detail.commitment);
  return `
    <div class="detail-heading">
      <div>
        <div class="eyebrow">Candidate meeting commitment</div>
        <h2>${escapeHtml(candidate.candidate_action)}</h2>
        <div class="muted">${escapeHtml(candidate.candidate_commitment_id)} · ${escapeHtml(candidate.classification)}</div>
      </div>
      <span class="badge ${admitted ? "ok" : "warn"}">${admitted ? "admitted" : "candidate"}</span>
    </div>
    <div class="cards">
      ${section("Candidate lineage", candidate)}
      <article class="card">
        <h3>Speaker qualification</h3>
        <p class="muted">A transcript label is not a principal. Use an existing verified Feishu identity binding; ambiguity remains blocked.</p>
        ${inputField("commitment-external-subject", "Feishu external subject", resolved ? String(detail.resolution?.external_subject ?? "") : "", "ou_xxx")}
        <label for="commitment-basis">Resolution basis (JSON)</label>
        <textarea id="commitment-basis" rows="4">${escapeHtml(JSON.stringify(detail.resolution ?? { reviewed: true }, null, 2))}</textarea>
        <button id="resolve-commitment-speaker" ${busy || admitted ? "disabled" : ""}>Resolve speaker identity</button>
      </article>
      <article class="card">
        <h3>Human admission</h3>
        <p class="muted">Only explicit self commitments can be admitted. Confirmation creates policy, approval, governance, responsibility, and a fixed-template draft.</p>
        ${inputField("commitment-due-basis", "Qualified due-time basis", candidate.candidate_due_text || "", "timezone and meeting context")}
        <label class="field" for="commitment-due-at"><span>Qualified due time</span><input id="commitment-due-at" type="datetime-local" /></label>
        <button id="confirm-commitment" ${busy || admitted || !resolved ? "disabled" : ""}>Confirm and admit commitment</button>
      </article>
      ${detail.commitment ? section("Commitment record", detail.commitment) : ""}
      ${section("Speaker resolution", detail.resolution)}
    </div>`;
}

function inputField(id: string, label: string, value: string, placeholder: string): string {
  return `<label class="field" for="${id}"><span>${escapeHtml(label)}</span><input id="${id}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" /></label>`;
}

function render(): void {
  const authenticated = Boolean(currentUser && !currentUser.expired);
  const queueMarkup =
    activeView === "intake"
      ? renderIntakeQueue()
      : activeView === "commitments"
        ? renderCommitmentQueue()
        : renderCaseQueue();
  const detailMarkup =
    activeView === "intake"
      ? selectedCandidate
        ? renderIntakeDetail(selectedCandidate)
        : `<div class="empty detail-empty">Select a candidate for human review.</div>`
      : activeView === "commitments"
        ? selectedCommitment
          ? renderCommitmentDetail(selectedCommitment)
          : `<div class="empty detail-empty">Select a meeting commitment candidate.</div>`
        : selected
          ? renderDetail(selected)
          : `<div class="empty detail-empty">Select an exception case.</div>`;
  root.innerHTML = `
    <header class="topbar">
      <div>
        <div class="eyebrow">Human Exception Operations Surface</div>
        <h1>Administrative Operations</h1>
      </div>
      <div class="topbar-right">
        <nav class="view-tabs" aria-label="Operations surface">
          <button id="view-intake" class="${activeView === "intake" ? "active" : ""}" ${authenticated ? "" : "disabled"}>Intake review</button>
          <button id="view-commitments" class="${activeView === "commitments" ? "active" : ""}" ${authenticated ? "" : "disabled"}>Meeting commitments</button>
          <button id="view-cases" class="${activeView === "cases" ? "active" : ""}" ${authenticated ? "" : "disabled"}>Exception cases</button>
        </nav>
        <div class="session">
          ${authenticated ? `<span>${escapeHtml(currentUser?.profile.sub)}</span><button id="logout">Sign out</button>` : `<button id="login">Sign in</button>`}
        </div>
      </div>
    </header>
    <main class="layout">
      <aside class="queue-panel">
        ${authenticated ? queueMarkup : `<div class="empty">Authenticate through OIDC to inspect governed operations.</div>`}
      </aside>
      <section class="detail-panel">
        ${errorMessage ? `<div class="error">${escapeHtml(errorMessage)}</div>` : ""}
        ${busy ? `<div class="loading">Loading current authoritative state…</div>` : ""}
        ${authenticated ? detailMarkup : `<div class="empty detail-empty">Sign in to access governed operations.</div>`}
      </section>
    </main>
    <footer>
      No force-complete, mark-success, evidence override, Kernel authorization, or provider retry controls exist in this console.
    </footer>
  `;

  root.querySelector<HTMLButtonElement>("#login")?.addEventListener("click", () => void login());
  root.querySelector<HTMLButtonElement>("#logout")?.addEventListener("click", () => void logout());
  root.querySelector<HTMLButtonElement>("#view-intake")?.addEventListener("click", () => switchView("intake"));
  root.querySelector<HTMLButtonElement>("#view-commitments")?.addEventListener("click", () => switchView("commitments"));
  root.querySelector<HTMLButtonElement>("#view-cases")?.addEventListener("click", () => switchView("cases"));
  root.querySelector<HTMLButtonElement>("#refresh-cases")?.addEventListener("click", () => void loadQueue());
  root.querySelector<HTMLButtonElement>("#refresh-intake")?.addEventListener("click", () => void loadIntakeQueue());
  root.querySelector<HTMLButtonElement>("#refresh-commitments")?.addEventListener("click", () => void loadCommitmentQueue());
  root.querySelector<HTMLButtonElement>("#save-intake-assessment")?.addEventListener("click", () =>
    void finalizeIntakeAssessment(),
  );
  root.querySelector<HTMLButtonElement>("#promote-intake-candidate")?.addEventListener("click", () =>
    void promoteIntakeCandidate(),
  );
  root.querySelector<HTMLButtonElement>("#resolve-commitment-speaker")?.addEventListener("click", () =>
    void resolveCommitmentSpeaker(),
  );
  root.querySelector<HTMLButtonElement>("#confirm-commitment")?.addEventListener("click", () =>
    void confirmCommitment(),
  );
  root.querySelector<HTMLButtonElement>("#authoritative-refresh")?.addEventListener("click", () =>
    void refreshAuthoritativeFacts(),
  );
  root.querySelector<HTMLButtonElement>("#append-qualification")?.addEventListener("click", () =>
    void appendQualificationAssessment(),
  );
  root.querySelectorAll<HTMLButtonElement>("[data-case-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const caseId = button.dataset.caseId;
      if (caseId) void selectCase(caseId);
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-candidate-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const candidateId = button.dataset.candidateId;
      if (candidateId) void selectCandidate(candidateId);
    });
  });
  root.querySelectorAll<HTMLButtonElement>("[data-commitment-id]").forEach((button) => {
    button.addEventListener("click", () => {
      const candidateId = button.dataset.commitmentId;
      if (candidateId) void selectCommitment(candidateId);
    });
  });
}

function renderDetail(detail: CaseDetail): string {
  const caseValue = detail.case;
  const status = String(caseValue.status ?? "unknown") as CaseStatus;
  const caseKind = String(caseValue.case_kind ?? "");
  const qualificationKinds =
    caseKind === "invoice-ap-preparation"
      ? ["vendor_qualification", "three_way_match"]
      : caseKind === "procurement-request"
        ? ["vendor_qualification"]
        : ["expense_policy_qualification"];
  const isFinancial = [
    "procurement-request",
    "invoice-ap-preparation",
    "expense-reimbursement",
  ].includes(caseKind);
  return `
    <div class="detail-heading">
      <div>
        <div class="eyebrow">${escapeHtml(caseValue.case_kind)}</div>
        <h2>${escapeHtml(caseValue.subject_ref)}</h2>
        <div class="muted">case ${escapeHtml(caseValue.case_id)} · epoch ${escapeHtml(caseValue.authority_epoch)}</div>
      </div>
      <div class="actions">
        <span class="badge ${statusClass(status)}">${escapeHtml(status)}</span>
        <button id="authoritative-refresh" ${busy ? "disabled" : ""}>Refresh authoritative facts</button>
      </div>
    </div>
    <div class="cards">
      ${section("Current case", caseValue)}
      ${section("Policy", detail.policy)}
      ${section("Governance basis", detail.governance)}
      ${section("Obligations", detail.obligations)}
      ${section("Kernel-backed effects", detail.effects)}
      ${section("Confirmed outcomes", detail.outcomes)}
      ${detail.evidence_links ? section("Evidence lineage", detail.evidence_links) : ""}
      ${detail.qualification_assessments ? section("Qualification assessments", detail.qualification_assessments) : ""}
      ${isFinancial ? `
        <article class="card">
          <h3>Record qualification assessment</h3>
          <p class="muted">This records a current, scoped qualification input. It does not authorize payment or settlement.</p>
          <label for="qualification-kind">Assessment kind</label>
          <select id="qualification-kind">
            ${qualificationKinds.map((item) => `<option value="${item}">${item}</option>`).join("")}
          </select>
          ${inputField("qualification-rule", "Rule reference", "", "m8-vendor-master-v1")}
          ${inputField("qualification-inputs", "Input references", "", "artifact:uuid,representation:uuid")}
          <label for="qualification-result">Result</label>
          <select id="qualification-result">
            ${["qualified", "incomplete", "mismatch", "ambiguous", "duplicate"]
              .map((item) => `<option value="${item}" ${item === "qualified" ? "selected" : ""}>${item}</option>`)
              .join("")}
          </select>
          <button id="append-qualification" ${busy ? "disabled" : ""}>Save qualification assessment</button>
        </article>` : ""}
      ${detail.audit === null ? `<article class="card"><h3>Audit</h3><p class="muted">Not disclosed to this principal. Audit authority is separate from operations visibility.</p></article>` : section("Audit", detail.audit)}
    </div>
  `;
}

function section(title: string, value: unknown): string {
  return `<article class="card"><h3>${escapeHtml(title)}</h3><pre>${pretty(value)}</pre></article>`;
}

void init().catch((error) => {
  errorMessage = error instanceof Error ? error.message : String(error);
  render();
});
