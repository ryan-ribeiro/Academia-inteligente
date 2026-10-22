# Fix — Approved Training Plan Session UI

## Status

Implemented on 2026-10-21 with automated verification passing. Scoped browser
verification for acceptance criterion 7 remains pending because no browser was
available through the session's UI tools. This task is not fully verified until
those viewport/keyboard checks are performed. `docs/requirements.md` remains
the sole canonical specification.

## Objective

Keep the A/B/C workout organization visible after a training sheet is approved,
in both the client and instructor areas. Improve the existing sheet-reading
area so users can identify each session and its exercises without interpreting
day suffixes inside a single long list.

The reported problem is that an unapproved sheet is separated into workouts
such as A, B, and C, while its approved presentation loses that organization.
Approval must preserve the readable session structure and the exact approved
prescriptions.

## Requirements covered

- RF-16: CA-16.1–CA-16.3, for the client's current-plan presentation.
- RF-15: CA-15.9, CA-15.12, and CA-15.13, only as the existing session-display
  contract and draft-preview regression boundary. AI generation is unchanged.
- RF-17: CA-17.3, for persistence across refresh; existing lifecycle and history
  behavior are integration constraints rather than new implementation scope.
- EXT-RF-INST-02: EXT-CA-INST-02.5–EXT-CA-INST-02.6, preserving instructor/date
  attribution; existing approval and authorization remain authoritative.
- EXT-RF-INST-03: EXT-CA-INST-03.3, for current/history content in the instructor
  collections. Existing collection scope and editing workflows are preserved.
- EXT-RF-LANG-01: applicable copy, accessible names, and localized metadata.

This is a presentation refinement of these requirements, not a new RF or a
redesign of client or instructor profiles.

## Related rules and constraints

- RN-04/RN-05: preserve role authorization and client data isolation.
- RN-16–RN-18: displaying or regrouping a sheet must not mutate approved
  content, create a version, or rewrite history.
- RN-31: keep the responsible instructor identifiable; historical attribution
  must remain attached to its original version.
- RNF01–RNF04: retain loading/error feedback, readable mobile layouts,
  accessible controls, and shared presentation logic with regression coverage.
- DEC-07, DEC-15, and EXT-DEC-INST-01: approval, activation, single-draft
  editing, responsibility, and immutable-history boundaries remain unchanged.
- DEC-16: use 360×800, 768×1024, and 1366×768 for scoped viewport verification.

## Required reading

Read `AGENTS.md`, this task, and:

- `docs/requirements.md`: the RF/CA and extension IDs above; RN-04/RN-05,
  RN-16–RN-18, RN-31; RNF01–RNF04; DEC-07, DEC-15, DEC-16,
  EXT-DEC-INST-01; sections 7.1.1 and 9.2 as applicable to training data.
- `docs/frontend-design.md`: shared theme/shells, Training, Instructor plan
  browsing, shared states, responsiveness, and accessibility.
- Tasks 15 and 32; `docs/tasks/instructor-plan-ui-review.md` and
  `docs/training-rebuild-and-session-display-2026-10-20.md` as supporting
  implementation history, not replacement requirements.
- The existing sheet renderers, session helper, DTOs, routes, and related tests
  listed below before editing.

If supporting history conflicts with the canonical requirements, stop the
affected part and request a human decision. Otherwise implement this bounded
presentation fix without expanding its product scope.

## Existing implementation and reproduction

The repository already contains partial support:

- `frontend/src/current-training-page.tsx` uses
  `frontend/src/training-sessions.ts` for both current plans and drafts. Its
  tests already cover current/draft A/B/C grouping and numeric legacy suffixes.
  Inspect the current branch and reproduce the remaining client gap before
  replacing working code or declaring this entire path missing.
- `frontend/src/components/training-plan-content.tsx` renders one flat exercise
  sequence. It is reused by instructor collection current/history details,
  pending previews, and the current-plan comparison in the append workflow.
- `frontend/src/instructor-plan-collections-page.tsx` is shared by Meus planos
  and Todos os planos. The instructor client workspace links into that detail;
  it does not need a second sheet renderer.
- `frontend/src/training-review.ts` defines `ReviewItem` without `position`;
  client `CurrentTrainingItem` includes it. A shared display helper must respect
  both ordering contracts without unsafe casts or API changes.

Reproduce using synthetic content with at least two exercises in each of A,
B, and C, including one exercise repeated across different sessions. Compare
the draft preview with the same content after the existing explicit instructor
approval. Open the current plan as its owner, in both instructor collections,
and through the instructor client workspace link. Refresh and reopen details.
Inspect a historical multi-session version as well. If the client grouping
already works, retain it and strengthen the missing cross-surface coverage.

## Exact implementation scope

### 1. Correct the existing reading surfaces

- Client: update or retain the approved/current sheet in Meu treino, using
  `current-training-page.tsx`. Keep the draft visually distinct from the active
  plan and preserve instructor name and approval date.
- Instructor: group approved/current sheet content in Meus planos and Todos os
  planos, including the same detail reached from Clientes. Retain the selected
  plan header, explicit client name, current/history status, and attribution.
- Historical detail uses the same grouping only when its retained content has
  session markers; it stays read-only and displays that version's own content.
- Preserve pending previews and the append comparison as affected consumers of
  the shared renderer. Do not change their editing or selection behavior.

Here, “client and instructor profiles” means their existing authenticated areas
where training sheets are displayed. Do not add training or health information
to social profiles, the instructor Perfil placeholder, or public pages.

### 2. Reuse one session interpretation

- Reuse or minimally generalize `training-sessions.ts`; do not add a second
  competing parser in the instructor component.
- Recognize the existing trailing `(Dia A)`, `(Dia B)`, `(Dia C)` convention
  case-insensitively and retain the helper's other supported letter labels.
  Preserve legacy `(Dia 1)` through `(Dia 7)` mapping to A through G.
- Show sessions in label order. For client items, preserve authoritative
  `position` order within each session; for review items without `position`,
  preserve their API array order. Restart visible numbering at 1 per session.
- Remove only recognized trailing day markers from display copies of exercise
  names. Preserve other parentheses, instructions, input objects, original
  names, positions, canonical equipment references, and persisted content.
- Keep repeated exercises in different sessions, even with identical
  prescriptions. Presentation must not deduplicate or redistribute exercises.
- If no item has a recognized session marker, render one ordinary session
  without inventing A/B/C divisions. If marked and unmarked items coexist, keep
  all unmarked items in an explicit `Exercícios sem ficha definida` section.
  Do not infer divisions from exercise muscles, plan titles, or array length.
- Display normalization must not feed back into save, approval, clone, or
  append payloads. Append selections must retain their original global item
  identity/order rather than using the restarted display numbering.

### 3. Improve the sheet in place

- Use visible, semantic session sections headed `Treino A`, `Treino B`, etc.,
  with a per-session exercise count and clear spacing/borders from the existing
  theme. Keep sections expanded so the division is immediately apparent.
- Organize each session as exercises followed by grouped sets,
  repetitions/duration, rest, load guidance, and recorded equipment. Preserve
  every prescription and existing source/limitation display where supplied.
- Reuse the existing MUI components and readable exercise cards/lists or table
  renderer as appropriate for the current surface. Consistency requires the
  same grouping and information hierarchy; a desktop-width table is not a
  requirement for the approved mobile view.
- Keep page and ordinary approved-sheet content free of horizontal overflow at
  the supported viewports. Preserve the existing accessible bounded scroll
  region if an affected draft table needs horizontal scrolling.
- Keep the established shells, list/detail navigation, selected-plan focus
  restoration, and separate approval-history tab. Do not add a new route,
  navigation destination, modal reading flow, or mandatory session selector.
- Use pt-BR application copy and accessible section names, logical heading
  levels, visible keyboard focus, and status text that does not rely on color.
- Update only the relevant training guidance in `docs/frontend-design.md` to
  document the shared session presentation after implementation.

## Out of scope

- AI prompts, providers, generation, validation, exercise selection, or new
  requirements for the contents of A/B/C.
- Backend services, endpoints, DTO contracts, database schemas/migrations,
  persisted session fields, data repairs, or rewriting existing plan names.
- Approval/activation rules, single-draft handling, concurrency, filters,
  pagination, authorization, and existing-draft replacement behavior.
- A profile-wide redesign, social changes, workout execution tracking, export,
  new dependencies, or unrelated refactoring.

Missing session markers in stored content are not permission to reconstruct or
modify an approved plan. Preserve the single-session/unassigned fallback and
report any separate data or backend defect with evidence before expanding scope.

## Acceptance criteria

1. A marked multi-session sheet displays separate, immediately visible A/B/C
   sections in the client's approved/current view and instructor current-plan
   details in both collections. Each exercise belongs to the same session as
   in its draft; numbering restarts per session.
2. Explicit approval followed by reopening/refreshing the current sheet retains
   all sessions, exercise order within them, prescriptions, and equipment.
   Current status, client identity where applicable, instructor, and approval
   date remain correct. An unapproved draft is never labeled current.
3. Historical multi-session content receives the same readable grouping using
   its own retained data and attribution, with no mutation controls added.
4. Single-session, mixed assigned/unassigned, numeric legacy, repeated-exercise,
   and instruction-parentheses cases follow the rules above without losing,
   duplicating, inventing, or changing items. Source inputs remain unchanged.
5. Pending preview, append comparison/selection, and existing draft editing and
   approval regressions pass after any shared-renderer change. Display
   numbering cannot change the exercises selected for append or saved content.
6. Loading, empty, error, and retry states remain usable. A current sheet and a
   simultaneous draft keep their content and status separate. Existing role
   and owner boundaries remain unchanged.
7. At 360×800, 768×1024, and 1366×768, the affected reading areas have legible
   session hierarchy, no clipped prescriptions or page overflow, appropriate
   accessible names, and usable keyboard navigation/focus.

These criteria operationalize the listed canonical requirements for this fix;
they do not replace their acceptance criteria.

## Tests and verification

- Add or extend focused session-helper/shared-content tests for grouping,
  ordered and positionless inputs, local numbering, legacy/unassigned cases,
  retained repetitions, preserved parentheses, and input immutability.
- Extend `current-training-page.test.tsx` and
  `instructor-plan-collections-page.test.tsx` with session-scoped assertions
  for exercise membership and complete prescriptions. Cover both instructor
  collection modes and historical detail, not just global A/B/C text matches.
- Add a mocked approval-to-current rendering regression using the same
  multi-session fixture before and after approval. No live AI or real client
  data is needed. Retain existing current/draft tests that already pass.
- Run the affected pending-plan, draft-field, and training-chat regressions
  when their shared dependencies change; verify that append selection still
  refers to the intended original items.
- From `frontend/`, run `npm test`, `npm run lint`, and `npm run build`, using
  the project's Docker Compose frontend service if that is the working local
  execution environment. Record actual commands and results.
- Perform scoped browser checks at all three viewports with synthetic data,
  including current/history reading and keyboard return focus. Record any
  unavailable browser verification as an explicit remaining limitation.
- Backend changes/tests are not expected for this presentation task. Report a
  demonstrated backend dependency before expanding scope.
- Run `git diff --check` and `git status --short`; review staged and unstaged
  diffs against the starting state. Preserve all pre-existing user changes.

## Completion requirements

Report the reproduced gap and resulting behavior, files changed, tests and
viewport checks executed with results, important decisions, and unresolved
issues. Distinguish verified results from pending checks. Update this task's
status only after implementation and verification. Do not commit or push.

## Implementation and verification record — 2026-10-21

### Reproduced gap and resulting behavior

The existing client current/draft grouping passed its baseline tests; it was
retained. Two new shared-content regressions failed before implementation:
instructor content had no named session regions, and numeric/mixed content was
still flat. Reproduction used synthetic fixtures and jsdom, not a live browser.

The shared instructor reader now shows expanded A/B/C sections, counts and
locally restarted numbering for current, historical and pending content and
append comparisons. Client session counts/headers remain consistent with it.
Unmarked sheets remain ordinary sessions; mixed unassigned items have their
own explicit section. Legacy days, additional letter labels, repeated exercises
and other parentheses retain their specified behavior.

The helper accepts client and positionless review items. Its `displayNumber`
does not overwrite original `position`; only display copies remove recognized
trailing markers. Approvals, saves and append selections retain their existing
contracts and original content. No backend, stored plan, AI, dependency, route
or authorization change was needed. Historical attribution and source displays
remain attached to their existing versions/surfaces.

### Files changed by this task

- `frontend/src/training-sessions.ts`
- `frontend/src/components/training-plan-content.tsx`
- `frontend/src/current-training-page.tsx`
- `frontend/src/training-sessions.test.ts`
- `frontend/src/components/training-plan-content.test.tsx`
- `frontend/src/current-training-page.test.tsx`
- `frontend/src/instructor-plan-collections-page.test.tsx`
- `frontend/src/instructor-pending-plans-page.test.tsx`
- `frontend/src/approved-training-session.test.tsx`
- `frontend/src/test/training-session-fixture.ts`
- `frontend/src/test/training-session-assertions.ts`
- `docs/frontend-design.md`
- `docs/tasks/fix-approved-training-session-ui.md`

### Commands and results

Commands ran from the repository root against the existing Docker Compose
frontend service, whose working directory is `/app`:

- `docker compose exec -T frontend npm test -- src/current-training-page.test.tsx src/instructor-plan-collections-page.test.tsx`: baseline **19 passed**.
- `docker compose exec -T frontend npm test -- src/components/training-plan-content.test.tsx`: **two expected failures before the fix**, reproducing the shared-reader gap.
- Focused helper/content/current/collection/pending/approval tests were run
  during implementation. The final suite includes **47 passing tests** across
  those six files.
- `docker compose exec -T frontend npm test`: **287 passed, one timeout** in
  the unrelated `client-management.test.tsx` registration test (5000 ms), while
  lint/build checks also ran. No training regression failed in this run.
- `docker compose exec -T frontend npm test -- --maxWorkers=1 --reporter=dot`:
  **288 passed across 42 files**, including client workspace links, pending
  approval/editing, draft fields and training chat; duration 168.84 seconds.
  Existing timeouts, assertions and test configuration were not relaxed.
- `docker compose exec -T frontend npm run lint`: **passed**, including the
  final source state.
- `docker compose exec -T frontend npm run build`: **passed**, including the
  final source state. Vite's existing non-fatal warning for a chunk above
  500 kB remains (approximately 833 kB before gzip).
- `git diff --check`, `git diff --cached --check`, `git status --short` and
  staged/unstaged diff review: **passed**. The 42 previously staged files
  remain staged as before; this task's changes are unstaged/untracked. No
  unrelated file was modified by this task. No commit or push was made.

The synthetic approval regression uses the same six exercises (two per session,
including a repeated exercise) before and after the explicit mocked instructor
approval. It checks owner reload, both collections, prescriptions, equipment and
attribution. Other regressions cover simultaneous current/draft isolation,
historical content/attribution, deep-link reopening, restored focus, input
immutability and original global append selection 5 despite local numbering.
Backend tests were not run because backend code/contracts did not change.

### Remaining verification

The UI-tool inventory returned no browsers; attempting to create an in-app
browser returned `Browser is not available: iab`. Consequently **no browser
viewport checks were performed** at 360×800, 768×1024 or 1366×768. Visual
hierarchy, clipping/overflow, visible focus and real keyboard return navigation
at all three sizes remain unverified. jsdom assertions cover named semantic
sections, heading levels and focus restoration, but do not establish actual
layout, browser keyboard behavior or comprehensive accessibility compliance.

## Original ready-to-run implementation prompt

Read `AGENTS.md`, then `docs/tasks/fix-approved-training-session-ui.md`, then
its Required reading. Inspect the current implementation and Git state before
editing; preserve pre-existing work. Implement only this approved/current
training-sheet presentation fix in the client and instructor reading areas.
Retain working client session support, reuse one session interpretation across
the affected renderers, and keep A/B/C sections visible after approval and on
refresh. Preserve exact prescriptions, unassigned/legacy content, responsible
attribution, immutable history, original append-selection positions, and all
existing approval/editing rules. Follow the established MUI visual system and
pt-BR UI language. Do not change AI, backend contracts, stored plans, profiles,
or dependencies. Run the specified regression, lint, build, and viewport checks;
review the Git diff and report files, results, decisions, and remaining issues.
Do not commit or push.
