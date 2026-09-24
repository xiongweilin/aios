# ADR 0006 — Meeting commitments and governed internal communication

Status: **accepted for the recorded isolated-staging scope; Admin PR #83 and
Gateway PR #16 merged; closure recorded in
`docs/acceptance/M9-staging-acceptance.md` and tag
`m9-accepted-2026-09-13`**

## Decision

M9 treats a meeting transcript as untrusted source material. The Feishu
intake profile `meeting.commitment.v1` may create zero or more candidate
commitments, but it cannot create authority, a Kernel responsibility, Work
admission, a communication command, or a fulfillment fact.

The Administrative domain owns candidate classification, EvidenceSpan
lineage, speaker-to-principal qualification, due-time qualification, human
admission, case state, communication metadata, and completion/discharge
coordination. A transcript speaker label is not a principal. A candidate is
blocked until a single current provider identity binding resolves it; zero or
multiple bindings remain ambiguous.

Only `explicit_self_commitment` candidates may be admitted. Assignments to
another person, aspirations, suggestions, information, and ambiguous
commitments remain non-authoritative candidates. Qualified due times must be
offset-aware; ambiguous relative times require a human basis.

Admission uses policy `meeting-commitment:m9-v1` and an
`administrative_operator` decision. Admission creates an AdministrativeCase
of kind `meeting-commitment` and a durable CommitmentRecord. The commitment
is a persistent responsibility proposal; it is not an Administrative Work
item and it does not authorize fulfillment.

M9 confirmation/reminder messages are fixed-template, one-to-one Feishu
communications. Draft content lives only in the content-addressed
ArtifactStore. Administrative database rows contain storage references,
digests, recipient identity, event identity, and delivery state. The Gateway
has a separate HMAC key from ingress/notification keys, accepts one durable
`communication_event_id`, and never treats transport acceptance as human read
or commitment fulfillment. A lost transport ACK is `outcome_unknown`; the
same event is reconciled rather than re-sent with a new identity.

Completion and responsibility discharge are separate. Fulfillment requires
the qualified committer's authorized attestation or an independently verified
objective evidence path. Discharge requires an assessment, an explicit
decision, and a Kernel lifecycle transition, in that order.

## Consequences

- M6 candidate/intake contracts remain reusable and old admission paths remain unchanged.
- Kernel receives only generic persistent-responsibility proposal objects and
  the generic capability `administrative.communication.message.send.v1`.
- The Gateway remains a transport boundary and does not own Administrative
  policy, identity, fulfillment, or completion.
- M9 cannot claim completion from a model response, a Feishu HTTP success, a
  provider message identifier, or a confirmation-message reply alone.

## Out of scope

Audio/ASR, meeting bots, calendar/email/SMS/Slack/group messaging,
marketing/legal/payment authority, delegated assignment, generic task
management, and M10 scope are not part of this ADR.
