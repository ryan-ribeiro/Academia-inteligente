# Training chat request replacement — 2026-10-19

Scope: RF-18/CA-18.1–18.8 and the existing RF-15 generation dependency,
particularly CA-15.6–15.12. RN-13, RN-15–RN-18, RN-23 and RN-29 remain
authoritative; RNF04/RNF06 apply. The canonical requirements are unchanged.

## Problem and correction

After a biceps sheet, an explicit full-body request could return the unchanged
biceps preview. Chat treated matching text in recent history as proof that the
saved proposal already fulfilled the request. A failed generation retains the
user's message, so resending it with a new request UUID triggered that shortcut
despite the proposal still containing the earlier biceps exercises.

Detailed exercise requests now run generation against their current text and
replace the content of the sole editable proposal. Text equality does not skip
generation. Replays of a completed request UUID still return its cached reply
without another provider call. Generic requests without new details retain the
existing draft guidance. New drafts are not duplicated, previous submission is
cleared when content changes, and approved plans remain untouched.

Live verification also exposed two writer-output failures on the exact full-body
request. The focus extractor abbreviated `todo o corpo` to the ungrounded
`todo corpo`; the focus instructions and correction now explicitly explain
full-body scope and its empty muscle list. Literal-term validation remains.
The writer also produced equipment descriptions without a paired catalogue UUID.
Instructions now explain the existing contract for free exercises and require a
valid description/UUID pair for machine-dependent content. No equipment, citation
or domain-validation rule was relaxed.

## Files changed

- `backend/app/modules/training/chat_service.py`
- `backend/app/modules/training/focus.py`
- `backend/app/integrations/ai.py`
- `backend/tests/test_training_targeted_requests.py`
- `backend/tests/test_training_rag.py`
- this report

Pre-existing working-tree changes were preserved. No dependency, provider, model,
database schema or frontend change was introduced; no commit or push was made.

## Verification

- Regression cases reproduced stale biceps content after failure and resend.
- **204 tests passed** in the final scoped suite, covering biceps-to-full-body replacement, provider and
  invalid-schema failures, same/new request UUIDs, the single-draft invariant,
  clearing previous instructor submission, current-plan preservation, full-body
  focus correction, citations and the shared adapter contract.
- Ruff lint, formatting checks and Git whitespace validation passed for the
  changed Python files.
- Separate live diagnostics used the original full-body request and authorized
  client context without printing health or identity data. Dispatch reached the
  writer with `scope=full_body` and the exact new request. After the prompt
  corrections, generation returned a validated four-exercise proposal with three
  canonical citations in **12.9 seconds**. Transactions were rolled back and
  persisted training version/revision/status/timestamp and item snapshots were
  verified unchanged. No test proposal was submitted or activated.

The live run checks routing and domain validation; it does not establish optimal
individual exercise selection or clinical superiority. A signed-in browser retry
was not performed. Instructor review remains required.

Command from `backend/`:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-dev.txt python -m pytest tests/test_training_targeted_requests.py tests/test_training_chat_generation.py tests/test_training_chat.py tests/test_training_generation.py tests/test_training_rag.py tests/test_training_selection.py tests/test_training_submission.py tests/test_ai_diagnostics.py -q
```

## Three-day generation rejection — 2026-10-20

The intermediate allowance for copying whole sheets documented in this section
is superseded by the owner's distinct-A/B/C clarification below. Its test and
live-generation results establish that intermediate behavior only.

Scope: RF-15/RF-18, particularly CA-15.13, CA-15.7, CA-15.10 and CA-18.4;
RN-13/RN-15/RN-16/RN-18/RN-23/RN-29 and RNF01/RNF04/RNF06 apply.

The local backend recorded two training-chat HTTP 422 responses with
`incomplete_training_plan` despite successful writer calls. The existing
completeness suite reproduced three failures: a corrected complete routine,
identical complete sheets with conservative evidence status, and server-assigned
day labels. All failed because the session-variation validator rejected an
otherwise complete day B when its exercises and prescriptions matched day A.
The older operational logs do not retain individual rejected prescriptions, so
they cannot prove the exact content of those two failed requests.

CA-15.13 explicitly permits the same exercise and prescription on different
assigned days. Removed the additional whole-sheet variation veto and its
assessment issue code. Writer and coverage-review instructions now evaluate
each day independently and allow applicable repeated prescriptions without
requiring artificial variety. The older exercise-selection paragraph in the
canonical specification was aligned with the existing CA-15.13 clarification.
No model, provider, dependency, database schema or review gate changed.

A separate live diagnostic then passed all three coverage assessments but failed
the final equipment validator. The local catalogue had no usable models; the
prompt alone did not prevent inconsistent equipment references. As a dependency
of this generation fix, structured decoding now permits either two null
equipment fields for free exercises or a description paired with a UUID from
the current usable-model catalogue. With an empty catalogue, both fields must
be null. This applies only to initial-generation envelopes; existing historical
reference handling and the authoritative domain validation remain unchanged.
Adapter regressions cover both providers and catalogue changes between calls.

Missing days, incomplete coverage, same-day duplicates, invalid citations and
unusable equipment remain rejected. All sheets are validated before the sole
draft changes; approved content remains unchanged. Regression assertions now
verify independent A/B/C assessment, identical complete prescriptions, no
unnecessary correction, conservative evidence aggregation and the unsubmitted
proposal state.

Changed files:

- `backend/app/integrations/ai.py`
- `backend/app/modules/training/completeness.py`
- `backend/app/modules/training/selection.py`
- `backend/tests/test_training_completeness.py`
- `backend/tests/test_training_rag.py`
- `docs/requirements.md`
- this report

Verification:

- **261 tests passed** across completeness, selection, RAG, generation, chat,
  targeted requests, submission, equipment usability, writing adapters and
  diagnostics. This includes the chat HTTP success path with three complete
  sheets and explicit instructor submission,
  UUID replay, cross-client isolation and preservation after failed generation.
- The **26 completeness tests passed** again after formatting. Ruff lint and
  formatting checks passed for all five changed Python files; Git whitespace
  validation passed.
- The local backend was restarted to load the correction; `/health` returned
  `{"status":"ok"}`.
- A separate final live diagnostic used synthetic onboarding, the configured
  local writer and the real PostgreSQL bibliography and equipment catalogue.
  It retrieved six passages and generated A/B/C, **five exercises per sheet**,
  with **three canonical citations** in **37.2 seconds**. Independent coverage
  assessments, requested sessions, duplicate selection, equipment references,
  final schema and citations all passed. There were no invalid equipment pairs
  or unknown model IDs. The transaction was rolled back, session mutation
  collections were empty and the persisted version/revision/status/timestamp
  snapshot remained unchanged. No real client's health context was used.

Earlier diagnostic attempts are not counted as complete validation: one used a
read-only transaction incompatible with the equipment validator's row locks,
and another was interrupted by the backend restart. The subsequent completed
run exposed the equipment failure above; the final run passed after the decoding
correction. These live diagnostics are separate from the fake-provider tests.

Automated command, from `backend/`:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-dev.txt python -m pytest tests/test_training_completeness.py tests/test_training_selection.py tests/test_training_rag.py tests/test_training_generation.py tests/test_training_chat.py tests/test_training_chat_generation.py tests/test_training_targeted_requests.py tests/test_training_submission.py tests/test_training_equipment_usability.py tests/test_openai_onboarding_adapter.py tests/test_ai_diagnostics.py -q --tb=short
```

Signed-in browser verification remains unperformed. Automated tests use fake
external providers; they do not establish the clinical quality or universal
reliability of the configured writer. Instructor review remains required.
No client proposal was submitted or activated by this investigation. No commit
or push was performed.

## Distinct A/B/C clarification — 2026-10-20

Scope: RF-15/RF-18 and the owner's clarification of CA-15.13 in this conversation.
RN-13/RN-15/RN-16/RN-18/RN-23/RN-29 and RNF04/RNF06 remain applicable.

The owner reported that all three sheets in the latest conversation were the
same. A read-only diagnostic confirmed identical normalized exercise selections
across the latest conversation's A/B/C draft; some prescription fields differed.
It printed only aggregate equality results, never client identity, health context
or conversation text. The previous correction incorrectly generalized permission
to repeat individual prescriptions into permission to copy entire sheets.

The canonical criterion now records the owner's clarification: each full-body
day must have a distinct exercise selection, with the evidence-based exception
currently recorded in CA-15.13. An identical selection requires a literal
recommendation from a retrieved reviewed passage, included in final citations,
plus the existing AI review's confirmation of client applicability. Generic
weekly frequency guidance and unsupported writer claims do not authorize
repetition; unavailable, expired or insufficient evidence cannot authorize it.
Individual exercises and their prescriptions may still recur. Merely changing day labels, order, spelling,
sets, repetitions, load instructions or rest does not satisfy this criterion.
Every day still independently requires full-body coverage and client-specific
restrictions; variety does not establish clinical superiority.

Generation compares each day's normalized exercise selection with every
previously validated day. Normalization is shared with same-day duplicate
validation. A repeated complete selection without the validated recommendation
receives one correction with the original request, evidence and prior sessions;
persistent unauthorized repetition or invalid
corrected citations preserves the saved draft and current approved plan.
Writer instructions now ask for distinct compositions and no longer anchor
every session to the same five example exercises. No arbitrary exercise
substitution is performed by backend code. Equipment decoding constraints from
the previous correction remain in place.

Tests cover exact copies, reordering, punctuation/case/accents, dosage-only
changes, one successful correction, failed correction, invalid final citations
and day C copying B rather than A. Recommendation-exception tests cover applicable
cited recommendations, generic frequency, unsupported claims, invented quotes,
unknown/uncited chunks, insufficient/expired/unavailable evidence, writer
uncertainty, restrictions and review outages. Positive fixtures retain shared individual
exercises while providing genuinely different day selections; HTTP preview,
idempotency and explicit submission checks remain.

Changed files in this follow-up:

- `backend/app/integrations/ai.py`
- `backend/app/modules/training/completeness.py`
- `backend/app/modules/training/selection.py`
- `backend/tests/test_training_completeness.py`
- `backend/tests/test_training_rag.py`
- `backend/tests/test_training_targeted_requests.py`
- `docs/requirements.md`
- this report

Verification:

- **283 tests passed** using the complete automated command in the preceding
  section. These tests use fake external adapters and do not call live providers.
- An initial live diagnostic remained blocked after correction because the
  configured writer copied day A into B. This is evidence of the rejection
  working, not successful generation of a distinct routine.
- Existing working-tree changes from the previous correction were preserved.
  No dependency, provider, model, database migration, commit or push was added.

Limits: text normalization does not independently identify anatomical synonyms
or prove clinical equivalence. Exercise recognition and semantic selection remain
the writer's responsibility, with instructor review required before activation.
Signed-in browser verification remains unperformed. Existing saved conversation
messages are not rewritten by the correction.

## Evidence-backed repetition exception — 2026-10-20

The owner's follow-up qualifies CA-15.13: A/B/C should differ by default, but
identical sheets may be appropriate when the knowledge base recommends them.
This supersedes the unconditional whole-sheet prohibition in the preceding
section, within the same RF-15/RF-18 scope and review boundaries.

The existing per-session AI review now optionally identifies a specific
recommendation to repeat the same sheet, with a passage ID, literal quote and
an explanation of applicability to the client's goal, experience and
restrictions. The backend requires the recommendation's passage to belong to
the current reviewed retrieval, its quote to match that passage, and its ID to
be included in the writer's final canonical citations. Generic weekly-frequency
guidance and a writer assertion alone do not authorize repetition. Missing,
outdated or unavailable retrieval, invented passages/quotes, absent citations,
review failure or unmet restrictions preserve the saved draft and current plan.
A recommendation does not upgrade a conservative overall evidence status or
prove that a routine is superior.

Distinct days continue to be compared by exercise selection, independent of
order, spelling and prescription fields. One correction reuses the same
request, evidence and previous sessions. Both existing writing adapters constrain
the new review field to retrieved passage IDs; with no passages or previous
sessions it must be null. No provider, dependency, public API, database schema or
activation permission was added.

The changed files remain those listed in the preceding section. The new
regressions cover explicit applicable recommendations, unsupported repetition,
generic frequency, forged quotes and IDs, uncited recommendations, conservative
evidence status, unavailable evidence, restriction failures, review outages,
atomic draft preservation and both adapter schemas. Semantic interpretation of
the quoted recommendation remains the existing AI reviewer's responsibility;
literal matching alone cannot establish applicability. Instructor approval
remains necessary. Existing saved conversations are not rewritten.

Separate synthetic live diagnostics exposed the local writer using resource
names such as “Peso corporal” as exercise names, then copying a complete day.
The repeated day was rejected with `repeated_session`, and transactions were
rolled back with persisted version/revision/status/timestamps unchanged. Writer
and review instructions now explicitly distinguish resources from exercises and
include several recognized complementary alternatives without prescribing a
fixed routine or an exercise count.

Final automated verification: **284 tests passed** using the complete command
above. Ruff lint and formatting checks passed for all six affected Python
files; `git diff --check` passed. The added regression also ensures that a
copied C sheet is corrected as `repeated_session` even when the reviewer
misclassifies its coverage.

Live limitations: the configured local writer produced distinct A/B selections
in a synthetic run but repeated B for C, without a supporting recommendation.
The response was rejected and persisted data remained unchanged. Another run
was rejected by the reviewer's coverage assessment. These runs do not constitute
a successful end-to-end generation of three distinct sheets. They demonstrate
controlled rejection and draft preservation; local model reliability remains
an unresolved limitation. No real client's onboarding was used in these live
generation diagnostics, and no client draft was replaced or submitted.
An isolated minimal-context coverage call recognized a complete sheet, so this
does not establish that all reviewer calls fail. The backend was restarted to
load the correction, and `/health` returned `{"status":"ok"}`. No commit or
push was performed.

Additional synthetic experiments with compacted previous-session context and
joint A/B/C generation also failed to establish reliable distinct routines.
The flat joint response omitted B/C; an experimental grouped schema filled
all days with identical movement-category labels instead of exercise names.
Those experimental generation strategies were not applied to application code.
The temporary diagnostic container was removed automatically. Final independent
verification again passed all **284 tests**, Ruff lint/formatting and Git
whitespace checks, with the backend health endpoint returning `{"status":"ok"}`.
