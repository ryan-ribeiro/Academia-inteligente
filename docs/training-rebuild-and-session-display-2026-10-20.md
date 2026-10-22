# Training rebuild focus and session display

Scope: the owner's reported rebuild validation failure (RF-15/RF-18,
CA-15.11 and CA-18.4) and session identification in Meu treino (RF-16,
CA-15.12/CA-15.13). RN-13, RN-15–RN-18, RN-23, RN-29–RN-31 and
RNF01–RNF04/RNF06 remain applicable. `requirements.md` remains canonical;
`frontend-design.md` governs the existing MUI presentation.

## Corrections

The live writer classified “Refaça todo a minha ficha de treino do zero,
para ganho de massa” as `full_body`, then retained that scope on correction.
Existing validation correctly rejected it because the request specifies no
muscle group or explicit full-body scope. Domain-derived allowed scopes now
accompany focus extraction and constrain both existing providers' decoding
schemas. Instructions distinguish rebuilding a whole sheet from requesting
full-body training and explain the `unspecified` result. Persistent invalid
scope or invented muscles still fail before retrieval or draft mutation.

Meu treino now groups existing `(Dia A)`/`(Dia B)`/`(Dia C)` item suffixes
under visible, accessible session headings in both current plans and drafts.
Numbered legacy days map to the same letters. Each session has its own
exercise numbering and each draft session has its own shared exercise table.
Display copies remove only the recognized day suffix and preserve prescriptions,
equipment, other parenthesized instructions and original within-session order.
Unassigned items remain visible in a separate section when mixed with days.
No saved plan content, approval requirement or API contract changes.

## Files changed in this follow-up

- `backend/app/integrations/ai.py`
- `backend/app/modules/training/focus.py`
- `backend/tests/test_training_focus.py`
- `backend/tests/test_training_targeted_requests.py`
- `frontend/src/training-sessions.ts`
- `frontend/src/current-training-page.tsx`
- `frontend/src/current-training-page.test.tsx`
- this report

Earlier changes, including the preceding rebuild-routing fix and staged
work, were preserved. No dependencies, model, provider, migration, commit or
push were added.

## Verification

- 293 fake-provider backend tests passed across focus, rebuild, chat,
  generation, targeted requests, submission, RAG, adapters and completeness.
- 24 frontend tests passed across Meu treino and training chat. Cases verify
  separate A/B/C sections, exercise membership, independent numbering, mixed
  unassigned items, numeric legacy days and preservation of input data.
- Ruff lint/format, TypeScript and Git whitespace checks passed.
- Separate live diagnostics with synthetic requests correctly extracted
  unspecified rebuild scope and targeted biceps scope using the configured
  local writer. A complete original-request generation with synthetic
  onboarding and the real bibliography/equipment catalogue produced a validated
  nine-exercise, three-citation unsubmitted draft in 37.68 seconds. The outer
  database transaction was rolled back; persisted training version IDs,
  revisions, statuses and update timestamps were verified unchanged.
- The local backend was restarted after the correction.

Limitations: no authenticated manual browser or viewport audit was performed.
The live synthetic generation verifies this request path, not universal model
reliability or individual clinical suitability. Instructor review remains
required; no real client's draft was generated, submitted or activated.
