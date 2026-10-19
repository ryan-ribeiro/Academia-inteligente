# Training assistant correction — 2026-10-18

This is an implementation and verification record, not a replacement for
`docs/requirements.md`. Scope: RF-15, RF-18, RF-19 and EXT-RF-INST-02;
particularly CA-15.2, CA-15.6–15.11, CA-18.2, CA-18.5–18.8, CA-19.5 and
EXT-CA-INST-02.9. RF-19 is an existing dependency whose confirmation flow is
preserved, not a new adaptation feature in this correction.
Client restrictions, client isolation and instructor approval remain authoritative.

## Findings and changes

1. The recent detailed full-body generation request went to ordinary chat
   because the client already had a current plan and the initial-request
   recognizer accepted only short phrases. Chat retrieval also appended the
   current plan's exercises, biasing the query toward those exercises. Explicit
   requests for a new complete routine now use the existing structured proposal
   generator, including their requested goal, frequency and division. Generic
   current-plan questions and adaptations keep their existing flow.
2. Combining general goals with onboarding restrictions in one retrieval query
   could fill the evidence window with clinical passages. Prescription retrieval
   now searches general training and the client's own restrictions separately,
   reserves room for both, removes duplicate passages and supplies at most six
   passages. Both searches retain existing review, license, freshness and client
   filters. An unavailable facet is reported conservatively.
3. Provider chat prose was capped at 600 characters, conflicting with the
   requested exercise table. Its bounded limit is now 16,000 characters.
   Previews rendered by the backend from validated domain content are separate
   from provider prose limits. Initial drafts and adaptations reuse one ordered
   table renderer with every requested column.
4. The adaptation button previously generated a proposal for the client's
   review; it did not submit to an instructor. That distinction was unclear,
   and the resulting complete exercise table was absent. Generation and sending
   now have explicit labels, a complete preview, pending/error/success feedback
   and duplicate-click protection. Generation retries retain their request UUID.
   Submission is verified through the client API and instructor pending list.
5. Adaptations that would remove every exercise are rejected before being saved
   or offered for submission. Attempting to generate an adaptation while a draft
   already exists returns a controlled conflict before calling the writer.

## Decisions

- Preserve the sole-draft rule and existing instructor approval/activation gate.
- A new routine remains a private proposal until its owner submits the displayed
  revision; the current plan remains intact throughout generation and submission.
- Include completed own-onboarding restrictions when generating an adaptation,
  regardless of whether its short reason happens to contain a health keyword.
- Preserve the configured writing and embedding providers, models, infrastructure
  and dependencies. No bibliography was added or relicensed.
- Preserve the pre-existing working-tree changes; do not commit or push.

## Owner clarification: muscle-targeted sheets

The intended output is a client-specific sheet matching the muscles requested,
not a default complete replacement routine. For example, “Que exercícios posso
fazer para ganho de massa muscular no bíceps?” produces a biceps sheet directly
in the conversation, including when the client already has a current plan.

- The existing AI adapter identifies muscle groups and the explicit goal before
  retrieval and structured generation. Empty muscle names are rejected. The
  writer receives the requested scope, completed own-onboarding restrictions and
  usable equipment. Only an explicit full-body request uses full-body scope.
- Exercise questions count as requests. Generic adaptation or execution questions
  retain conversational support and the existing RF-19 confirmation boundary.
- The client sends the exact displayed revision using **Enviar rascunho para
  minha revisão**. This submits it directly to instructor review, without another
  generation or client-acceptance step. New AI changes require a fresh submission.
- Instructors preview the suggested sheet and current plan, explicitly select
  generated exercises, and prepare a combined draft. Existing exercises and
  their order remain intact; selected additions retain their source order.
  Explicit approval alone activates the new version.
- A new focused request also reuses a draft previously created to edit the
  current plan. It becomes a standalone sheet with the same draft ID, leaving
  the approved base intact and retaining the append option. If that draft came
  from an accepted adaptation, its original operations remain as superseded
  history. The chat refreshes that history after replacement.
- Failed, stale and cross-client appends leave the current plan intact. If an
  instructor edit saves successfully before an append fails, the screen retains
  the saved revision so the append can be retried without saving the edit twice.

The additional implementation and regression files for this clarification are
`backend/app/integrations/ai.py`,
`backend/app/modules/training/{chat_service,generation_service,review_service,router,schema,service}.py`,
`backend/tests/test_training_targeted_requests.py`,
`backend/tests/test_training_chat.py`,
`backend/tests/test_training_review_postgres.py`,
`frontend/src/{instructor-pending-plans-page,training-chat-page}.tsx`, their test
files, `frontend/src/training-review.ts`, and
`frontend/src/components/training-draft-review-actions.tsx`. The canonical
criteria and presentation guidance are in `docs/requirements.md` and
`docs/frontend-design.md`.

## Changed files

- `backend/app/integrations/ai.py`
- `backend/app/modules/training/adaptation_service.py`
- `backend/app/modules/training/chat_service.py`
- `backend/app/modules/training/generation_service.py`
- `backend/app/modules/training/knowledge_query.py`
- `backend/app/modules/training/presentation.py`
- `backend/app/modules/training/router.py`
- `backend/tests/test_training_chat_generation.py`
- `backend/tests/test_training_rag.py`
- `frontend/src/training-adaptation.ts`
- `frontend/src/training-chat-page.tsx`
- `frontend/src/training-chat-page.test.tsx`
- `docs/training-assistant-debug-2026-10-18.md`

## Earlier verification, before the muscle-targeted clarification

- Backend training, lifecycle, review, equipment and knowledge suites: 192 passed;
  four PostgreSQL-only equipment cases skipped in this ordinary run.
- Explicit PostgreSQL run covering chat, review, collections, equipment and
  knowledge: 23 passed, including those four equipment cases.
- Frontend chat, current-training, table rendering and knowledge-source suites:
  29 passed.
- Ruff check and format check passed for all changed Python files.
- Frontend TypeScript compilation and production build passed. Vite retains its
  existing warning about a bundle larger than 500 kB.
- Git whitespace validation passed.
- A diagnostic using the configured local writer and real bibliography retrieved
  six passages, including Biga anatomy and NHS strength alongside restriction
  references, and generated a nine-exercise proposal with the required table.
  Its transaction was rolled back, and the unchanged persisted version count
  was verified. No test draft was submitted to a real instructor.

This earlier evidence does not verify the later muscle-targeted clarification.
Evidence is still limited to
the reviewed catalogue excerpts; retrieval does not establish an optimal
individual dose. Automated tests use fake external adapters; the live diagnostic
is separate from those tests. Manual visual verification in a signed-in browser
was not performed. Existing conversation messages are retained; new requests use
the corrected flow.

## Muscle-targeted clarification verification

The following checks were executed after the owner clarified the targeted-sheet
and instructor-append behavior:

- Backend: **215 passed, 7 skipped**. The skipped cases require explicit isolated
  PostgreSQL execution; Docker's Linux engine was unavailable on this host.
  The executed cases include biceps/quadriceps/multiple-muscle requests with and
  without a current plan, broader explicit full-body scope, completed-onboarding
  restrictions, focus-provider failure, idempotency, direct client submission,
  instructor authorization, selected-exercise append, stale and cross-client
  rejection, transaction rollback, and replacement of existing instructor or
  accepted-adaptation drafts without changing approved content.
- Frontend: **46 passed** across chat, current training, pending instructor review,
  structured chat rendering and knowledge-source components. This includes
  direct submission of the displayed revision, selected appends followed by
  separate approval, stale-state handling, saved-edit retention after append
  failure, and refreshed superseded-adaptation feedback. An initial parallel run
  timed out in an existing editor test; the complete scoped suite passed without
  file parallelism, preserving the existing test timeout and assertions.
- Ruff checks and formatting checks passed for the changed Python files.
- TypeScript and the production frontend build passed. The existing Vite warning
  about a chunk larger than 500 kB remains.
- Git whitespace checks passed. Pre-existing unrelated changes were preserved;
  the temporary `uv.lock` generated during environment setup was removed.
- No new live-writer, signed-in browser or PostgreSQL verification was performed.
  The earlier live full-body diagnostic above does not validate targeted output.

Backend command, from `backend/`:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-dev.txt python -m pytest tests/test_training_targeted_requests.py tests/test_training_submission.py tests/test_training_chat.py tests/test_training_chat_generation.py tests/test_training_generation.py tests/test_training_review.py tests/test_training_rag.py tests/test_training_lifecycle.py tests/test_training_adaptations.py tests/test_training_equipment_usability.py tests/test_training_collections.py tests/test_training_review_postgres.py -q
```

Frontend commands, from `frontend/`:

```powershell
npm.cmd test -- src/instructor-pending-plans-page.test.tsx src/training-chat-page.test.tsx src/current-training-page.test.tsx src/components/training-chat-content.test.tsx src/components/training-knowledge-sources.test.tsx --maxWorkers=1 --no-file-parallelism
npm.cmd run build
```

## Validation rejection and approved local model change — 2026-10-19

Scope: the reported RF-18 validation error and its existing RF-15 generation
dependency, CA-15.11–15.12, CA-18.4, RN-16/RN-23/RN-29, RNF04 and RNF06.
No new feature, dependency or approval bypass was introduced.

The failed turn returned HTTP 422 after successful focus extraction and two
successful generation calls. This path is consistent with the exercise-selection
correction being exhausted. Its original rejected output was not retained, so
its exact rows cannot be reconstructed. Existing diagnostics reported only
`draft_blocked` with reason `none` and zero retries.

Repeated diagnostics using the owner's biceps request and a synthetic onboarding
profile exposed broader output-quality problems with the configured local
`qwen3:1.7b`: calf exercises appeared in biceps sheets, and exercise labels and
repetitions were inconsistent. Setting temperature to zero did not resolve the
problem; that experimental setting was not applied. Schema validation alone does
not establish anatomical relevance or scientific superiority.

The already installed `qwen3:4b` returned a biceps-focused sheet in the comparison.
The owner explicitly approved switching the local writing model. Only the ignored
local `.env` model selection was changed; the backend was recreated to load it.
The approval is recorded in `docs/requirements.md`. Providers, adapters,
embeddings, bibliography, timeout and review gates remain unchanged.

Diagnostics now allowlist separate reasons for rejected focus, duplicate
exercises, invalid plan structure, citations and equipment. Corrective focus and
selection attempts count as retries. Focus extraction is classified as training
generation rather than `unknown`. Logs contain categories and counts, never raw
requests, prescriptions, identities or validation exception text.

Files changed in this follow-up:

- `.env` (ignored local configuration; never committed)
- `backend/app/integrations/ai_diagnostics.py`
- `backend/app/modules/training/chat_service.py`
- `backend/app/modules/training/generation_service.py`
- `backend/app/modules/training/focus.py`
- `backend/app/modules/training/selection.py`
- `backend/tests/test_ai_diagnostics.py`
- `backend/tests/test_training_selection.py`
- `backend/tests/test_training_targeted_requests.py`
- `docs/requirements.md`
- this report

Verification:

- **153 tests passed** across AI diagnostics, exercise selection, targeted
  requests, generation, chat and RAG. Assertions cover retry classification,
  unchanged drafts after failure, and absence of sensitive input from logs.
- Ruff lint and formatting checks passed for all eight changed Python files.
- Git whitespace checks passed. Pre-existing changes were preserved; no commit
  or push was performed.
- After recreating the backend, `/health` returned `{"status":"ok"}` and its
  configured writing model was confirmed as `qwen3:4b`.
- A separate live diagnostic executed the owner's original request through focus
  extraction, retrieval, complete plan validation, citation resolution and
  equipment validation, using the owner's existing authorized context without
  printing it. It returned a two-exercise proposal and two accepted citations in
  **7.9 seconds**. The transaction was rolled back; the complete persisted
  version/revision/status/timestamp snapshot was verified unchanged. No draft was
  submitted or activated.

Limits: a successful live attempt does not establish reliability for every
request or clinical superiority of its prescription. Signed-in browser retry was
not performed. The existing instructor review remains necessary.

Final automated command, from `backend/`:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-dev.txt python -m pytest tests/test_ai_diagnostics.py tests/test_training_selection.py tests/test_training_targeted_requests.py tests/test_training_generation.py tests/test_training_chat.py tests/test_training_rag.py -q
```

## Exercise selection and resumed verification

Scope: RF-15/RF-18, particularly CA-15.11–15.12. Generated sheets and AI draft
edits must select the best-supported applicable alternative(s), rather than
concatenating one prescription per retrieved passage. The writing instructions
compare evidence quality, outcomes relevant to the requested goal and client
applicability; retrieval order, citation count and publication age alone do not
establish superiority. Unsupported comparative claims remain prohibited.

- A shared selection validator rejects repeated normalized exercise names in
  the same or unspecified day, even with different sets, repetitions, load or
  equipment. Different prescriptions across explicitly labelled `(Dia A)` and
  `(Dia B)` remain visible in the existing exercise column. Distinct complementary
  exercises remain possible. Text normalization does not establish semantic
  equivalence between differently named exercises.
- Redundant output receives one correction using the original request and the
  same evidence. The backend validates the complete corrected sheet and final
  citations; it does not automatically retain the first row. Persistent
  duplicates or invalid citations leave the saved draft intact.
- A live diagnostic exposed expansion of a biceps-only request into biceps,
  triceps and shoulders during focus analysis. Before retrieval, the backend now
  checks that returned muscle/region labels appear as complete terms in the
  original request, allowing differences in accents, case and whitespace. The
  extractor retains the client's terms rather than replacing them with synonyms.
  Invalid focus receives one correction; persistent invalid focus fails before
  retrieval or writing. This guard does not anatomically classify arbitrary text
  or independently interpret negation.

Files for this correction:
`backend/app/integrations/ai.py`,
`backend/app/modules/training/{focus,selection,generation_service,chat_service}.py`,
`backend/tests/test_training_selection.py`,
`backend/tests/test_training_targeted_requests.py`,
`docs/requirements.md`, and this report. Earlier unrelated working-tree changes
were preserved. No dependencies, configured providers or models were changed.

Verification after resuming:

- **148 backend tests passed** across exercise selection, generation, chat,
  targeted requests and RAG. Coverage includes correction without arbitrarily
  selecting the first candidate, explicit day assignments, invalid final
  citations, unchanged drafts after failure, invented muscle labels, correction
  before retrieval, word boundaries, case, accents and whitespace.
- Ruff lint, formatting and Git whitespace checks passed.
- The live diagnostic used a synthetic onboarding profile and the actual
  PostgreSQL bibliography, inventory and configured Ollama `qwen3:1.7b` writer.
  With the corrected extractor, focus was exactly biceps with the requested
  muscle-gain goal. Retrieval returned six passages. The writing call then failed
  with controlled `timeout_or_network` at its configured 120-second timeout
  (127.1 seconds total including extraction and retrieval). The live complete
  sheet and semantic exercise selection therefore remain **unverified**.
- Both diagnostic sessions were rolled back, and the unchanged training-version
  count was verified. No client draft or instructor submission was created.
  The earlier fake-adapter tests remain separate from this live diagnostic.
- The local backend service was restarted to load the changed modules (its
  Uvicorn command does not enable reload). `/health` returned `{"status":"ok"}`.

Final automated command, from `backend/`:

```powershell
uv run --no-project --python 3.13 --with-requirements requirements-dev.txt python -m pytest tests/test_training_selection.py tests/test_training_generation.py tests/test_training_chat.py tests/test_training_targeted_requests.py tests/test_training_rag.py -q
```

## Chat disappearing while generation is pending

Scope: RF-18/CA-18.1–18.4 and the existing RF-15 generation dependency, RN-29,
RNF01, RNF02 and RNF06. The reported symptom was an exercise request receiving
no visible reply while the page appeared to reload.

The client routing effect reset `onboardingComplete` to `null` whenever the
session object changed, including successful access-token renewal. On the
assistant route, that replaced and unmounted the chat with a preparation screen.
The in-flight request, processing indicator and eventual result/error therefore
belonged to a discarded component. The effect now revalidates onboarding in the
background while preserving its loaded value for an active session. Missing or
expired sessions still clear the value; logout and idle-session policy remain
enforced.

Backend operational logs independently showed training-generation attempts
timing out twice at 120 seconds, with complete chat turns taking approximately
248–274 seconds. Synthetic diagnostics with the configured `qwen3:1.7b` also
produced repetitive/invalid output. Those incomplete outputs were never saved.
Relaxing local decoding schema bounds or using generic JSON mode did not resolve
the generation problem; neither experiment was applied to application code.

Verification of the UI correction:

- The regression test reproduced the missing processing indicator before the
  change, then passed after it. It starts a real App/chat render, sends a request,
  renews the token while onboarding revalidation is delayed, and verifies that
  the pending message/input survive and the final success **or 503 error** remains
  visible without navigation.
- **97 frontend tests passed** across application routing, session lifecycle,
  authentication, redirects and training chat. The existing `app.test.tsx` logout
  test needs its expected development OIDC issuer in the test environment; the
  initial run without it failed with `Invalid URL`, and the full suite passed
  with that issuer configured, without changing the test or authentication code.
- TypeScript and the production build passed. The pre-existing large-bundle
  warning remains.

Changed application/test files for this UI correction:
`frontend/src/app.tsx` and `frontend/src/app-session.test.tsx`, plus this report.

Commands, from `frontend/`:

```powershell
$env:VITE_OIDC_ISSUER = 'http://localhost:8080/realms/academia'
npm.cmd test -- src/app-session.test.tsx src/app.test.tsx src/auth.test.ts src/auth-redirects.test.ts src/training-chat-page.test.tsx --maxWorkers=1 --no-file-parallelism
npm.cmd run build
```
