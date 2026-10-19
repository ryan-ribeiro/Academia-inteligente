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
