# Academia Inteligente — Canonical Implementation Requirements

This is the sole canonical specification for future implementation. It
preserves every requirement identifier and acceptance criterion while
integrating approved decisions and explicitly labeled product extensions.

**Coverage:** all 33 original functional requirements and 110 functional
acceptance criteria, 6 non-functional requirements and 18 non-functional
acceptance criteria, 37 business rules, 10 technology entries, 18 original DEC
questions, approved chronological decisions, and 5 approved product-extension
requirements.

**Authority:** This document is the only source of implementation requirements.
`docs/decisions.md` and `docs/product-extensions.md` retain supporting history
and detail, but do not override this specification. If they appear to conflict,
stop the affected task and request a human decision before changing this file.
`docs/implementation-plan.md` and `docs/tasks/` define execution order and
verified status, but do not create product requirements by themselves.

`docs/frontend-design.md` governs UI presentation and reuse; it does not add or
change RF/CA/RNF/RN requirements or their acceptance status.

Implementation documentation, task prompts, code identifiers, and API contracts
remain in English. The language of user-facing application UI is governed by
EXT-RF-LANG-01 in section 3.1.

Unchecked acceptance boxes preserve requirement traceability; they are not evidence
that a criterion is unimplemented or failed. Current verified status appears in
section 9.3 and is based only on completed tasks and test evidence.

## 1 Context and usage guidance

### 1.1 Product purpose and vision

Centralize and automate gym administrative, financial, and service operations,
improving establishment control and the preparation of client-specific training
plans. The system is both an administrative platform and a client-facing gym
application.

The domain includes client and employee registration, authentication and
permissions, onboarding, training plans and AI interactions, biometrics and
physical access, attendance and occupancy, charges and plans, administrative
indicators, classes, equipment, and the approved limited client-facing
extensions.

The intended client journey is:

`registration → Keycloak provisioning → secure credential setup → login → local
client resolution → personal area → onboarding → training-plan generation →
current-plan view → AI assistant → later client modules`.

Later modules may include occupancy, equipment, financial/agenda functions,
progress sharing, and opt-in visible presence according to their own scope and
decision gates. This journey expresses dependencies; it does not move every
stage into the original MVP.

### 1.2 How to interpret this document

The requirement catalog notes that some requirements may not be needed yet, may be
classified incorrectly, or may differ from what the professor requested. It
does not identify every such item. The items are therefore retained, and
conflicts are recorded in section 9. An item's presence here does not
automatically place it in the next delivery.

| Identifier | Meaning |
| --- | --- |
| RF-01 to RF-33 | Functional requirements. |
| CA-XX.Y | Acceptance criterion associated with an original functional requirement. |
| RNF01 to RNF06 | Non-functional requirements with their original numbering. |
| CA-RNFXX.Y | Original non-functional acceptance criterion. |
| RN-01 to RN-37 | Business rules with their original identifiers. |
| TEC-01 to TEC-10 | Identifiers added to reference the ten technology-table entries. |
| DEC-01 through DEC-18 | Original decision questions; section 9 records which are now resolved and which remain open. |
| EXT-RF-* / EXT-CA-* | Approved additions from `docs/product-extensions.md`, never original RF/CA identifiers. |

The requirements and criteria were reorganized with spelling adjustments,
without removing conditions. Implementation notes, the suggested sequence, and
open questions are identified as guidance from this consolidation.

### 1.3 Instructions for Codex

1. Read this file before planning functionality and identify the affected RF,
   extension requirements, RNF, RN, decisions, and acceptance criteria.
2. Work within the current task's scope. Use the MVP in section 8 as a priority
   reference while respecting its dependencies and open questions.
3. Apply relevant business rules and non-functional requirements even when a
   task names only one RF.
4. Do not silently decide among technology alternatives, conditional items, or
   questions in this specification. Resolve only open items that affect the task and
   continue work independent of them.
5. Preserve identifiers so tasks, changes, and validation remain traceable to
   requirements.
6. Use acceptance checkboxes for tracking: mark an item only after its behavior
   has been implemented and verified.
7. Do not expand scope by inferring a complete feature from a diagram or a rule
   that lacks a detailed functional flow. Record the need and link it to the
   corresponding decision.
8. Follow the workflow constraints and task system in the implementation plan.
9. For client-owned protected resources, derive the local account/client from
   the authenticated Keycloak `sub`; a browser-supplied `client_id` is never
   proof of ownership.

## 2 Actors and responsibilities mentioned

| Actor or term | Responsibility indicated by the requirements |
| --- | --- |
| Client or student | Enter and view their own data, access the training plan and chat, purchase a plan, and consult information made available by the gym. |
| Attendant | Perform service activities and register a client's facial photo according to permissions. |
| Instructor, teacher, or professional | Evaluate AI suggestions, modify training plans, and create training manually; remain identifiable as responsible for plans they create or change. |
| Administrator or administrative user | Carry out authorized administrative operations. |
| Employee | Category used in registration and authorization requirements; its responsibilities must be distributed among operational roles. |
| Visitor | Consult available equipment under RF-33. |

DEC-04 resolves the current role baseline: Keycloak realm roles are `client`,
`employee`, `attendant`, `instructor`, and `admin`; attendant and instructor are
specialized employee roles. Permissions not expressly supported below remain
undefined rather than implicitly granted.

### 2.1 Authorization matrix

| Role | Approved capability boundary |
| --- | --- |
| Client | Authenticated self-service for the client's own onboarding, current training plan, AI conversation, and later explicitly approved client features. No administrative APIs. |
| Employee | Base workforce identity only; no blanket access to health, biometric, financial, or administrative data. Concrete operations require an approved specialized permission. |
| Attendant | Employee specialization; may manage biometric enrollment when RF-22 exists, but may not access health/medical onboarding data. |
| Instructor | Employee specialization; may access health information only when functionally required for approved training-plan review/work, and remains attributable under RN-31. |
| Admin | Approved administrative operations such as client management. Admin status alone does not grant unrestricted access to health or biometric data. |
| Visitor | Only public behavior explicitly approved, currently equipment consultation under RF-33 when implemented. No protected client data. |

Backend authorization is authoritative and independent from frontend route or
control visibility. Employee/admin identities are not publicly registered: the
initial administrator is realm-bootstrapped from environment configuration,
and employees are provisioned by the authorized RF-07/RF-08 administrative
flow approved under EXT-DEC-INST-01.

**Local demo initialization amendment (RF-04/RF-05, 2026-10-21):** the local
Docker Compose startup automatically creates `admin@academia.test`,
`cliente@academia.test`, `funcionario@academia.test`, `atendente@academia.test`,
and `instrutor@academia.test`, with the requested initial demo password `123`.
Their roles are respectively `admin`, `client`, `employee`,
`employee` + `attendant`, and `employee` + `instructor`. This is a local-only
exception to administrative provisioning, controlled by `SEED_DEMO_ACCOUNTS`
and `DEMO_ACCOUNT_PASSWORD`; production does not enable it. Credentials remain
exclusively in Keycloak. Client and instructor identities include their required
local domain records and synthetic person data. Generic employee and attendant
identities receive no new operational capabilities or instructor registration.
Acceptance: initialization creates all five usable linked identities, resumes
interrupted provisioning without duplicating users, preserves completed accounts'
passwords/data/activation on restart, refuses to take over unrelated identities,
and does nothing when demo initialization is disabled. This does not enable public
registration or bypass authorization, onboarding, or biometric access gates.

### 2.2 Approved authentication and identity model

- `account.id` and `client.id` are independent application-generated UUIDs.
- `account.keycloak_subject` is the unique external Keycloak OIDC `sub`; it is
  never the account or client primary key.
- `account.email` is normalized, authoritative, and globally unique even for
  inactive accounts. It is not duplicated as an authoritative client field.
- `account.account_active` alone controls application-login eligibility. It is
  separate from enrollment/payment/biometric state and physical gym access.
- `client.account_id` is a unique foreign key, establishing one Account ↔ Client
  relationship. Client-domain data belongs to Client, not Account.
- Credentials remain exclusively in Keycloak. PostgreSQL stores no password,
  temporary password, required-action token, or authentication secret.
- Keycloak-hosted login, first-access, password, informational, and related
  authentication pages use the repository-managed `academia` login theme. They
  remain server-rendered by Keycloak and follow the shared visual, responsive,
  accessibility, and `pt-BR` conventions in `docs/frontend-design.md`; this
  does not move credential handling into the React application. **Origin:**
  approved implementation decision — `docs/decisions.md` DEC-03 Keycloak
  login-theme amendment.
- An active browser session renews OIDC access tokens with refresh-token
  rotation only while activity continues. Five consecutive minutes without
  browser activity ends the session. Tokens are kept only in browser
  `sessionStorage`, cleared on timeout, refresh failure, or sign-out, and never
  stored in PostgreSQL, URLs, or logs. **Origin:** approved decision —
  `docs/decisions.md` DEC-04 session-renewal amendment.
- Administrative client creation first persists the local Account/Client pair
  and a durable, per-client provisioning record. It reports a distinct pending
  state while an independent background reconciliation provisions or updates
  one Keycloak identity with matching e-mail, adds the `client` role, preserves
  any independently active approved `instructor`/`employee` roles on a matched
  dual-role Account, persists its `sub`, and starts Keycloak's secure
  first-access required action for a new identity so the person defines their
  password. A pending client cannot use the client role, and one pending
  identity never blocks another administrative registration.
- Public self-registration is disabled. Creating a client never grants an
  administrative or employee role.
- Cross-system partial failures require explicit compensation or durable,
  idempotent reconciliation. A null-subject local account is not assumed usable.
- Protected client behavior resolves `sub → account → client` server-side and
  rejects inactive, unlinked, unauthorized, or cross-client requests.

The same Account abstraction is used by client and employee identities; it is
not client-specific credential storage. One Account may be linked to both a
Client and an Employee when the normalized e-mail and CPF identify the same
person. Client and employee activation are independent. Backend policy must
check the active domain role as well as the authenticated Account, and Keycloak
role reconciliation must remove only the deactivated specialization while
preserving any other active role.

## 3 Functional requirements

The 33 requirements below retain their numbering and all their
acceptance criteria. “Outside the stated MVP” means only that an item is not in
the original MVP list; it remains in the requirement catalog.

### RF-01 Register client

**Scope:** stated MVP.

Allow an administrative user to register a new client and link the client to an
e-mail address.

**Acceptance criteria**

- [ ] **CA-01.1:** with valid required fields, the system creates the client and generates a unique identifier.
- [ ] **CA-01.2:** an e-mail already associated with a different person or an
  incompatible account is rejected; the matching dual-role case in CA-01.5 is
  not treated as a duplicate person.
- [ ] **CA-01.3:** invalid fields return a validation message, and no partial registration is created.
- [ ] **CA-01.4:** registration captures first name, surname, normalized e-mail,
  mathematically validated CPF, phone number, CEP, street, number, optional
  complement, neighborhood, city, and state; Client has no CNPJ field.
- [ ] **CA-01.5:** matching e-mail and CPF may attach a Client to an existing
  Employee Account without duplicating the person or removing the employee's
  active specialized role; conflicting e-mail/CPF identity is rejected.

### RF-02 View and search clients

**Scope:** stated MVP.

Allow administrative users to find and view registered clients.

**Acceptance criteria**

- [ ] **CA-02.1:** the administrator can list clients.
- [ ] **CA-02.2:** a search by name or e-mail returns matching records.
- [ ] **CA-02.3:** an unauthorized user cannot view third-party data.

### RF-03 Update client data and status

**Scope:** stated MVP.

Allow changes to basic registration data and client activation/deactivation.

**Acceptance criteria**

- [ ] **CA-03.1:** valid changes persist after reloading the page.
- [ ] **CA-03.2:** a deactivated client is no longer treated as an enabled user.
- [ ] **CA-03.3:** deactivation does not automatically erase the client's history.
- [ ] **CA-03.4:** enabled clients need a valid facial photo for biometrics.
- [ ] **CA-03.5:** an administrator can update every field accepted at client
  registration, and valid changes persist after reload.
- [ ] **CA-03.6:** name/e-mail and active-role changes are durably reconciled
  with Keycloak; deactivating the Client removes client authorization but does
  not remove an independently active Employee specialization on the same
  Account.

**Consolidation note:** CA-03.4 depends on RF-22 biometrics, which is not in the
stated MVP. The relationship among an active client, an enabled client, a valid
photo, and payment needed definition under DEC-05; the approved result and
deferral are recorded in section 9.

**Approved Brazilian contact/address policy for RF-01, RF-03, RF-07, and
RF-08:** store CEP, street (`logradouro`), number, optional complement,
neighborhood (`bairro`), city (`localidade`), and two-letter state (`UF`). This
matches the standard address elements documented by Correios. ViaCEP is the
approved free CEP lookup adapter. It may prefill only values actually returned
by the service; every address field remains manually editable, number remains a
manual field, and lookup not-found, invalid input, timeout, rate limiting, or
provider failure must produce a controlled Portuguese state without blocking
manual entry or corrupting existing form values. Validate the normalized
eight-digit CEP before the external request. Keep the adapter server-side,
bounded by timeout, and replaceable; do not treat ViaCEP as authoritative
person data or make registration availability depend on it. Phone input accepts
Brazilian presentation formatting, is normalized for persistence, and must
represent a valid 10- or 11-digit national number.

### RF-04 Authenticate user

**Scope:** stated MVP.

Identify a client, employee, or administrator before allowing access to
protected areas.

**Acceptance criteria**

- [ ] **CA-04.1:** valid credentials for an active user start an authenticated session.
- [ ] **CA-04.2:** invalid credentials do not start a session.
- [ ] **CA-04.3:** protected routes without a valid session return an unauthenticated state.

### RF-05 Authorize functions by role

**Scope:** stated MVP.

Separate Client, Employee, and Administrator permissions.

**Acceptance criteria**

- [ ] **CA-05.1:** a client cannot access administrative functions.
- [ ] **CA-05.2:** an administrator can access the specified administrative operations.
- [ ] **CA-05.3:** a direct call to a forbidden API is rejected, even without using the interface.

**Consolidation note:** The requirements also mention attendants and instructors.
Their permissions need detail without assuming that all employees have the same
access; see DEC-04.

### RF-06 Recover access by e-mail

**Scope:** approved post-MVP implementation — 2026-09-27.

Allow recovery of an account linked to an e-mail address.

**Acceptance criteria**

- [ ] **CA-06.1:** a valid request generates a recovery message.
- [ ] **CA-06.2:** an expired or previously used token is rejected.
- [ ] **CA-06.3:** after recovery, the user can authenticate with the new mechanism/credential.
- [ ] **CA-06.4:** the SMTP server must be isolated in a Docker container.

**Consolidation note:** CA-06.4 is a technical deployment constraint for the
e-mail service, retained for traceability and also recorded in section 6.2.
DEC-03 records the SMTP versus e-mail API choice.

**Approved recovery policy (DEC-06, 2026-09-27):** administrators can request
recovery from a provisioned client's administrative details; authenticated
clients can request it for their own Account from profile settings. Both send
Keycloak's `UPDATE_PASSWORD` action email to the linked account's registered
email. The user approved a 15-minute (900-second) link lifetime. Keycloak owns
password entry, expiry and single-use validation; no password or recovery token
is received or stored by React or the application database. The existing
Keycloak version and sign-in flow are retained. A request does not activate an
account, change roles, or immediately replace its password.

The backend verifies ownership/administrator authorization and requires an
active, linked Account with no pending identity reconciliation. It verifies the
Keycloak identity's email before delivery. Admin and self-service share a
persistent 60-second per-account resend cooldown, including uncertain delivery.
Provider failures return a controlled error without an automatic resend or false
success. A success means Keycloak accepted the email send, not that the password
has already changed. Local development continues to use isolated Mailpit SMTP.

**Login-screen recovery amendment — 2026-09-27:** the user also requested an
unauthenticated email-entry action on the login screen. Enable Keycloak's native
"Esqueceu sua senha?" flow in the existing `academia` theme. Its reset-credentials
action links expire after 900 seconds, configured specifically for that action
type. The screen confirms requests generically for known and unknown email
addresses and never exposes a public application endpoint accepting target
account IDs. Password entry, token validation and delivery remain in Keycloak.
The application cooldown above applies to the authenticated admin/profile
actions; the public flow uses Keycloak and deployment authentication protections.
Existing realms receive a targeted configuration update without reimporting
users, changing credentials, or upgrading Keycloak.

### RF-07 Register employee

**Scope:** outside the stated MVP.

Allow basic employee registration.

**Acceptance criteria**

- [ ] **CA-07.1:** an administrator can create an employee with the required data.
- [ ] **CA-07.2:** the employee receives a unique identifier.
- [ ] **CA-07.3:** an incompatible duplicate account/e-mail is rejected.
- [ ] **CA-07.4:** registration records first name, surname, normalized e-mail,
  mathematically validated CPF, phone number, CEP, street, number, optional
  complement, neighborhood, city, state, optional CNPJ, and the specialized
  role; the only employee specialization currently assignable is `instructor`.
- [ ] **CA-07.5:** registration uses the durable Keycloak reconciliation and
  secure first-access delivery flow; PostgreSQL stores no employee password or
  first-access credential.
- [ ] **CA-07.6:** when e-mail and CPF match one existing client Account, the
  employee profile may be linked to that same person and receive the
  `instructor` role without duplicating identity data or removing `client`.

**Approved registration-data policy:** reusable personal data belongs to one
Account-linked person record: first name, surname (which may contain spaces),
globally unique CPF, phone, and Brazilian address. CPF is stored normalized to
digits and validated with its official check-digit calculation; repeated-digit
placeholders are invalid. Employee-only data contains optional CNPJ and the
specialized employee role. An optional CNPJ is normalized and check-digit
validated but is not globally unique because more than one employee may be
associated with the same organization. A conflicting e-mail/CPF combination
must be rejected rather than joining two people.

### RF-08 View, update, and deactivate employee

**Scope:** outside the stated MVP.

Maintain registered employees' data and status.

**Acceptance criteria**

- [ ] **CA-08.1:** an administrator can list and view employees.
- [ ] **CA-08.2:** valid changes persist.
- [ ] **CA-08.3:** a deactivated employee loses permissions linked to the account.
- [ ] **CA-08.4:** an administrator can update every field accepted at employee
  registration, with shared personal-data changes reflected consistently in a
  linked Client profile.
- [ ] **CA-08.5:** name/e-mail and active-role changes are durably reconciled
  with Keycloak; a client/instructor account retains the other active role when
  one domain role is deactivated.

### RF-09 Send onboarding invitation by e-mail

**Scope:** stated MVP.

Send a registered client an e-mail containing a link for the first onboarding.

**Acceptance criteria**

- [ ] **CA-09.1:** triggering the invitation sends a message to the linked e-mail address.
- [ ] **CA-09.2:** the link points to that client's onboarding.
- [ ] **CA-09.3:** a delivery failure is recorded as a failure, not as completion.

**Administrative UI amendment:** client registration and detail/edit panels do
not expose the redundant "Enviar convite de onboarding" action. Clients reach
their pending onboarding after login. The invitation API and existing secure
links remain supported.

### RF-10 Access onboarding through a secure link

**Scope:** stated MVP.

Open the form from the link received by e-mail.

**Acceptance criteria**

- [ ] **CA-10.1:** a valid token opens the corresponding form.
- [ ] **CA-10.2:** an invalid or expired token is rejected.
- [ ] **CA-10.3:** a token cannot open another client's onboarding.

### RF-11 Record physical data

**Scope:** stated MVP.

Record the physical details specified in the approved form to guide training.

**Acceptance criteria**

- [ ] **CA-11.1:** all physical fields defined in the onboarding schema can be completed and persisted.
- [ ] **CA-11.2:** fields marked as required are validated.
- [ ] **CA-11.3:** reopening the form correctly retrieves saved data while it remains editable.

**Consolidation note:** The approved schema, required fields, and their validation are not fully defined; see DEC-06.

### RF-12 Record client medications and health conditions

**Scope:** stated MVP.

Record the medical information mentioned in the meeting, including complaints, medications, and prior problems/conditions reported by the client.

**Acceptance criteria**

- [ ] **CA-12.1:** the form has identifiable areas for complaints, medications, and relevant history/problems.
- [ ] **CA-12.2:** submitted data is associated only with the correct client.
- [ ] **CA-12.3:** a user without permission cannot obtain this information through the interface or API.

### RF-13 Validate and complete onboarding

**Scope:** stated MVP.

Mark the form complete when the client finishes providing the required information.

**Acceptance criteria**

- [ ] **CA-13.1:** a form with incomplete required fields cannot be completed.
- [ ] **CA-13.2:** on completion, the system records the completion state and date/time.
- [ ] **CA-13.3:** the AI can identify that valid onboarding is available.

### RF-14 View own onboarding

**Scope:** outside the stated MVP.

Allow the client to review the data they provided.

**Acceptance criteria**

- [ ] **CA-14.1:** an authenticated client views only their own onboarding.
- [ ] **CA-14.2:** displayed values match the persisted content.
- [ ] **CA-14.3:** access to another client's onboarding is blocked.

### RF-15 Generate a training plan using AI

**Scope:** stated MVP.

Generate initial guidance/a training plan using the information provided during onboarding.

**Acceptance criteria**

- [ ] **CA-15.1:** an attempt without completed onboarding does not generate a plan.
- [ ] **CA-15.2:** with valid onboarding, a successful AI call produces a structured, persistable plan.
- [ ] **CA-15.3:** the plan is associated exclusively with the client who requested/received the generation.
- [ ] **CA-15.4:** relevant health data influences the AI proposal. Under the approved Task 14 interpretation of DEC-07, it does not automatically block proposal generation; mandatory instructor review is the safety gate before approval or activation.
- [ ] **CA-15.5:** the plan is created based on each client's onboarding data.
- [ ] **CA-15.6:** AI generation creates a `proposal` only when the client has no existing `proposal`; it must not create a second draft for that client.
- [ ] **CA-15.7:** initial generation retrieves at most six relevant, reviewed,
  commercially reusable knowledge passages. Persisted proposals carry backend-
  validated `citations`, `knowledge_status`, and `knowledge_limitations`; an
  invented or unretrieved reference prevents persistence.
- [ ] **CA-15.8:** the instructor review displays the proposal's bibliographic
  grounding and limitations. Sources never bypass client restrictions or the
  exclusive `instructor` approval and activation gate.
- [ ] **CA-15.9:** generated client previews show `Treino A — [division name]`,
  the student's stated goal in plain Brazilian Portuguese, the unapproved
  instructor-review status, and an ordered table of exercise, sets, repetitions
  or duration, individual load guidance, and rest in seconds. The response
  retains `citations`, `knowledge_status`, and `knowledge_limitations`.
- [ ] **CA-15.10:** an initial AI draft enters professional review only after
  its owner explicitly clicks to submit the displayed revision. Submission
  never approves or activates it. Unsatisfied clients can request changes;
  a subsequent AI edit requires a fresh submission. Instructor-authored drafts
  and explicitly client-accepted adaptations retain their existing review flow.
- [ ] **CA-15.11:** exercise requests, including questions such as which exercises
  to use for biceps hypertrophy, identify the requested muscle groups and goal
  through the configured AI adapter before retrieval. A targeted request returns
  a structured client-specific sheet for those groups; it is not widened into
  a full-body routine. Explicit full-body requests retain their broader scope.
- [ ] **CA-15.12:** AI sheets and AI draft edits consolidate competing prescriptions
  of the same exercise instead of adding a row per source, repetition range, load,
  or equipment alternative. Selection prioritizes evidence quality, relevant
  outcomes and applicability to the requested goal and client constraints, not
  retrieval order or citation count. Complementary exercises may remain; evidence
  without comparative results must not be described as proving superiority.
  Repeated exercises with different prescriptions require explicitly identified
  different days in the displayed sheet. A sheet without day assignments is one
  session. Redundant output is corrected once against the same request/evidence;
  unresolved duplicates fail without changing the saved draft or approved plan.
- [ ] **CA-15.13:** following the owner's 2026-10-19 clarification, a full-body
  request for three days produces three complete sheets, A, B and C. Every
  sheet independently covers the requested full-body scope with recognizable,
  complementary exercises adapted to the client's restrictions. Three days
  must not become three exercises or a single two-exercise sheet. No fixed
  universal exercise count or claim of optimal individual prescription is
  implied. Requested sessions and per-session completeness are checked before
  persistence; incomplete output receives one correction with the same request
  and evidence. Persistent gaps or review-provider failure preserve the saved
  draft and approved plan. Client and instructor previews show each day's own
  ordered exercise table; repeating an exercise in explicitly different days
  is allowed, including the same prescription. Following the owner's
  2026-10-20 clarification, A/B/C must have distinct exercise selections rather
  than copying an entire sheet, unless the retrieved, reviewed evidence
  explicitly recommends repeating the same sheet across days and the existing
  AI review confirms applicability to the client's goal, experience and
  restrictions. This exception requires a literal recommendation quote from a
  currently retrieved passage included in the final canonical citations;
  generic frequency guidance or an unsupported writer claim is insufficient.
  Unavailable, outdated or insufficient retrieved evidence cannot authorize
  repetition. A valid specific recommendation does not upgrade a conservative
  overall evidence status or establish superiority of the routine.
  Changing only order, spelling, sets, repetitions, load guidance or rest does
  not make a day distinct. Compare each
  session with all previously generated days, correct a repeated selection once
  with the same request and evidence, and preserve saved content if correction
  fails. Individual exercises may still recur; variation must retain full-body
  coverage and client restrictions without claims of clinical superiority.
  Instructor approval remains necessary.

**Consolidation note:** Apply RN-12 through RN-19 and RN-29 through RN-31. DEC-07 resolves the current proposal/review flow: AI may create only a structured proposal, and an instructor must review it before approval or activation.

### RF-16 View current training plan

**Scope:** stated MVP.

Display the client's current plan in a format usable especially on a mobile phone.

**Acceptance criteria**

- [ ] **CA-16.1:** a client with a plan can view the current version.
- [ ] **CA-16.2:** a client without a plan receives an appropriate empty state.
- [ ] **CA-16.3:** one client cannot view another client's plan.

### RF-17 Persist and version the training plan

**Scope:** stated MVP.

Keep the generated plan and create a new version when dynamic changes take effect.

**Acceptance criteria**

- [ ] **CA-17.1:** the first generation creates the initial version.
- [ ] **CA-17.2:** an effective change creates a subsequent version and identifies it as current.
- [ ] **CA-17.3:** refreshing the page does not lose the current version.
- [ ] **CA-17.4:** a client has at most one plan version in `proposal` state at any time, regardless of whether AI or an instructor created it.

**Consolidation note:** Versioning must also preserve previously completed workouts and identification of the responsible professional, as required by RN-18 and RN-31.

### RF-18 Converse with the AI assistant

**Scope:** stated MVP.

Provide a chat where the client can discuss their training and provide additional context.

**Acceptance criteria**

- [ ] **CA-18.1:** an authenticated client sends a message and receives a response.
- [ ] **CA-18.2:** the assistant receives context from the current plan and, when needed, that client's onboarding.
- [ ] **CA-18.3:** one client's messages do not appear in another client's conversation.
- [ ] **CA-18.4:** provider unavailability returns a controlled error and does not corrupt the training plan.
- [ ] **CA-18.5:** when the client has a `proposal`, the AI may edit only that sole draft; its authority does not depend on whether AI or an instructor created the draft.
- [ ] **CA-18.6:** every training-chat turn and AI draft replacement uses the
  shared retrieval and reference-validation contract below; assistant messages
  persist their canonical citations and show a Portuguese "Fontes" section.
- [ ] **CA-18.7:** unavailable retrieval, missing relevant evidence, and expired
  source reviews produce explicit limitations. The assistant must not fabricate
  references, infer diagnoses, or present unsupported clinical conclusions.
- [ ] **CA-18.8:** a direct request for exercises generates the structured sheet
  in the conversation, including when a current plan exists. The displayed
  **Enviar rascunho para minha revisão** action sends that exact draft revision
  directly to instructor review; it does not merely start another client-review
  generation step. The client receives sent, pending and failure feedback.

**Approved RAG contract (RF-15/RF-18/RF-19):** PostgreSQL with `pgvector`
stores a versioned bibliographic catalogue, reviewed passages, and 1024-
dimensional dense embeddings from BGE-M3 through a separate Ollama embedding
adapter. The existing writing-LLM adapters, provider selection, and model
configuration remain unchanged except for the approved local selection below.

The owner approved replacing the local `qwen3:1.7b` writing-model selection
with the already installed `qwen3:4b` on 2026-10-19 after training-generation
diagnostics. This local configuration decision preserves the writing adapters,
provider selection, embedding model, and instructor-review gates.

Hybrid retrieval combines PostgreSQL full-text
search and vector cosine similarity with bounded rank fusion and relevance
filtering, returning zero to six passages. Shared bibliographic sources contain
no client records. Any client-scoped passage must match the authenticated
client UUID before either search and ranking; conversation/onboarding context
remains limited to that client's existing authorized scope. No client queries,
health facts, or chat transcripts enter the shared corpus or its logs.

Only sources explicitly marked reviewed, commercially reusable, with an
allowed OGL-3.0, CC-BY-4.0, or CC-BY-SA-4.0 license and a valid review deadline
can contribute passages. Pending authorization, NC licenses, excluded content,
and expired reviews are filtered before retrieval. Publication age alone does
not establish obsolescence: the review deadline determines freshness. Expired
passages cannot support a response even when they would otherwise match.

Retrieved passages are untrusted reference data, never instructions. The
writer returns `citations` as retrieved passage IDs and a `knowledge_status`
claim. The backend rejects unknown IDs and invalid status claims and fills
the canonical citation metadata from the retrieved records, never from
writer-supplied author/title/URL values. Empty citations cannot become
`supported`. The public/persisted contract contains canonical `citations`,
`knowledge_status` (`supported`, `insufficient_evidence`, `outdated`, or
`unavailable`), and a Portuguese `knowledge_limitations` string. Status and
limitations must conservatively reflect retrieval quality; a matching source
does not establish a diagnosis or applicability to every client. Evidence
snapshots accompany proposals and their adaptation-to-review drafts without
exposing raw client chat to instructors. Manual instructor content changes
clear any AI citations whose applicability has not been revalidated.

`backend/app/modules/knowledge/catalog.json` is the packaged seed source.
Every normal `docker compose up --build` runs schema migrations followed by
an idempotent catalogue/chunk/embedding bootstrap before the backend starts.
The dedicated embedding model is downloaded into persistent Ollama storage.
Both fresh databases and existing volumes receive catalogue updates; identical
passages retain their embeddings, changed content is re-embedded, and revoked
or removed passages stop being retrievable. A failed bootstrap fails startup
visibly instead of announcing a ready backend with missing seed knowledge.
After startup an embedding/search outage returns `unavailable` with a clear
limitation and does not corrupt plans or disable independent features.

**Initial source review:** all fourteen submitted candidates are retained as
bibliographic metadata. Only selected text from the nine sources below is
indexed; this is a technical review of content and reuse conditions dated
2026-10-13, not clinical approval of any individual plan. The pilot stores
selected original English NHS excerpts and translated research/textbook
summaries with attribution, capture date, adaptation notices, and license
links. Images, video, logos, and third-party materials are not ingested.

| Indexed source | Reuse and evidence boundary |
| --- | --- |
| [NHS strength](https://www.nhs.uk/live-well/exercise/strength-exercises/), [flexibility](https://www.nhs.uk/live-well/exercise/flexibility-exercises/), [balance](https://www.nhs.uk/live-well/exercise/balance-exercises/) | OGL-3.0 original text snapshots with attribution/capture date; [NHS exceptions and attribution terms](https://www.nhs.uk/our-policies/terms-and-conditions/) apply. Publisher review deadlines remain 2027-02-28, 2026-11-20, and 2026-11-07 respectively. General guidance, not individual prescriptions. |
| [Biga et al., Anatomy & Physiology](https://open.oregonstate.education/anatomy/) | [CC BY-SA 4.0](https://open.oregonstate.education/anatomy/back-matter/creative-commons-license/); translated section 10.6 summaries retain the same license. Foundations, not a clinical guideline. |
| [Rojas-Jaramillo et al., 2024](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2024.1477796/full) | CC BY; deep-squat review excluded populations with knee pathology. No extrapolation to reported knee pain or injury. |
| [Verville et al., 2023](https://link.springer.com/article/10.1007/s10926-023-10124-4) | CC BY 4.0; chronic primary low-back-pain population and modality-specific uncertainty must remain explicit. |
| [Pavlova et al., 2023](https://bjsm.bmj.com/content/57/20/1327) | [CC BY 4.0 reuse verified](https://pmc.ncbi.nlm.nih.gov/articles/PMC10579176/); dose reporting is incomplete and aggregate associations do not determine safe individual loads. |
| [Wu et al., 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12011739/) | [CC BY at publisher](https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2025.1560597/full); clinical shoulder population and heterogeneous exercise outcomes. |
| [Lin et al., 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12234485/) | [CC BY at publisher](https://www.frontiersin.org/journals/rehabilitation-sciences/articles/10.3389/fresc.2025.1596966/full); low-certainty knee-osteoarthritis evidence, not a diagnosis from a complaint. |

The Brazilian Ministry of Health guide, Open Textbook of Exercise Physiology,
and BMJ knee-exercise review remain metadata-only because their supplied
licenses are NC. WHO and JOSPT guidelines remain metadata-only pending reuse
authorization. Their content is never embedded or supplied to a writing LLM.
Research/textbook selections have an annual technical review deadline of
2027-10-13. Any future ingestion requires the same source/license checks.

Focused verification covers grounding/reference validation in all three AI
flows, real PostgreSQL `vector(1024)` and hybrid-search behavior, idempotent
bootstrap, client segregation, expiration and provider failures, plus source
display in chat and instructor review. Tests use fake embedding/writing
adapters; they do not rely on live external AI providers.

**Approved implementation policy (DEC-08/DEC-18, Task 16):** training chat is
a separate client-owned persisted conversation. Responses are conversational
Brazilian Portuguese and never directly mutate a current, approved, or
historical training plan/version. A
response may carry a non-binding persisted adaptation-suggestion signal for the
Task 17 confirmation flow; it is not a plan patch or proposal. Context is
limited to the authenticated client's current approved
plan, relevant own completed-onboarding facts when necessary, bounded summary,
and bounded recent messages. Raw messages and summary are client-only and
eligible for cleanup after 30 days; this does not affect authoritative plans or
plan history. The frontend UUID idempotency and one-retry provider policy apply;
Ollama retains its configurable local timeout. Any actual plan change remains
the Task 17 proposal/review flow.

**Approved single-draft rule:** a client may have at most one training-plan
`proposal` at a time. AI generation and an instructor may each create that
draft only when no `proposal` already exists for the client. Repeated AI
generation requests reuse the existing draft rather than creating another one.
While that sole draft remains in `proposal`, the client may clearly request
changes through the training chat. The AI may edit that draft regardless of
whether AI or an instructor created it, but it may edit no other plan state.
The provider returns a complete structured replacement, which the backend
validates using the authoritative training-plan schema and applies with
concurrency protection. The AI never edits an approved, current, superseded,
or historical version, and never approves or activates a plan; instructor
review remains mandatory.

**Client submission amendment (RF-15/RF-18, 2026-10-17):** generation and
submission for instructor review are separate. A generated initial draft is
visible to its client before submission, but is excluded from instructor
pending lists, draft details, edits, and approval. Only the owning active
client can submit its current revision; stale or cross-client requests fail.
AI changes clear submission and increment the revision. Instructor changes
to submitted content preserve review readiness. The single-proposal constraint
still includes unsubmitted drafts. Existing initial AI drafts without evidence
of client confirmation also require submission; instructor drafts and retained
client-confirmed adaptations remain reviewable. Instructor approval remains the
sole activation gate, and RAG evidence is retained through submission.

**Confirmation-loop correction (RF-15/RF-18):** when no current plan exists,
an explicit initial-plan request or a short affirmative reply to the immediately
preceding assistant's single initial-plan confirmation question invokes the
existing RF-15 generation service. Completed authoritative onboarding remains
required. The backend reuses any existing proposal and saves a newly generated
proposal atomically with the chat reply and request UUID; retries must not
create duplicate drafts. It reports success only after validated persistence,
with a pointer to Meu treino and the mandatory instructor-review boundary.
Negative, conditional, unrelated, or ambiguous replies do not authorize generation.
Current-plan adaptations retain the RF-19 confirmation and review flow.

**Muscle-targeted exercise request amendment (RF-15/RF-18, 2026-10-18):**
the owner clarified that a request for exercises is not necessarily a complete
replacement routine or a pathology adaptation. The AI identifies the muscles
and goal stated in the request, retrieves evidence for that scope, and generates
the client-specific structured sheet immediately. Questions asking which
exercises to perform count as requests. Completed own onboarding and equipment
constraints remain applicable. A new explicit focus can revise the sole draft;
identical repeated requests reuse it. Only the owner's subsequent submit click
sends the displayed revision to the instructor. No second generation or client
acceptance step is inserted after that click. This explicit-request flow is
distinct from unsolicited RF-19 adaptation offers described below.

The writing context retains passage IDs, source title, section, text and
limitations; full canonical attribution and licensing metadata remains on the
backend for citation validation and display. Ollama training requests use an
explicit 16,384-token context so reviewed passages and client restrictions do
not displace the requested muscle focus under its smaller server default.
The configured provider and model are unchanged.

**Exercise-selection clarification (RF-15/RF-18, 2026-10-18):** retrieved
passages are candidate evidence, not a list of prescriptions to concatenate.
The writer selects the best-supported applicable alternative(s), consolidating
synonymous/redundant movements and retaining only useful complementary choices.
The existing flat item contract displays explicitly planned day assignments
using an `exercise_name` suffix such as `(Dia A)` or `(Dia B)`; a frequency in the
plan title alone does not assign exercises to days. The backend rejects repeated
normalized exercise names in the same or unspecified day, even when prescription
fields differ. As clarified by CA-15.13, individual identical prescriptions may
repeat across explicitly assigned days, but full-body A/B/C sheets must have
distinct exercise selections unless the cited, reviewed recommendation and
applicability checks in CA-15.13 authorize repetition, while satisfying each
day's scope and client restrictions. Semantic
equivalence and evidence comparison remain the writer's responsibility; text
normalization is not a semantic or clinical ranking. Correction reuses retrieved
evidence and revalidates final citations, without adding providers or changing
approved/historical plans.

**Mandatory automatic exercise review amendment (RF-15/RF-18/RF-19,
2026-10-21):** every newly AI-generated sheet, chat draft replacement and
resulting adaptation sheet requires automatic review before persistence or
display as a generated proposal, regardless of full-body, targeted or unspecified
scope. Use the existing provider-independent assessment adapter and the same
client-scoped request, onboarding restrictions, equipment and retrieved evidence.
Each actual session must identify recognizable exercises compatible with the
requested scope. Resource-only labels such as `Peso corporal`, `Halteres` and
`Barra`, including day suffixes, are invalid exercise names; the backend rejects
these obvious cases independently of the model. A targeted sheet must not be
required to cover unrelated full-body movement patterns. Preserve the full-body
coverage and variation rules when that scope is requested. Rejected output may
receive one correction using the same request/evidence and must be reviewed
again; persistent invalidity, missing/malformed assessments or reviewer outages
prevent saving/publishing the new content and preserve existing drafts, approved
plans and history. Ordinary conversation without a proposed sheet needs no
assessment. Reusing an unchanged existing draft does not generate new content.
Following the owner's legacy-draft correction on 2026-10-21, reuse must first
reject obvious invalid exercise names in the persisted sheet. A generation
request for such a draft regenerates the same sole editable draft and applies
the complete automatic review, even without an explicit replacement flag or
detailed chat instruction. Failed regeneration preserves the stored draft for
correction, but client projections mark it invalid with `validation_error`, omit
its generated preview, hide its exercise table and provide a regenerate action.
Invalid persisted sheets cannot be submitted or approved. Existing approved and
historical content remains unchanged; a failed correction must not turn invalid
cached content into a successful generation response. Valid unchanged drafts
retain their existing reuse behavior.
The incident's live writer/reviewer check also exposed resource-prefixed labels
such as `Peso corporal — Pressão de joelho` and ambiguous `Flexão de perna`.
For new AI content, separate resource prefixes followed by a colon or dash from
an explicitly named movement, preserving the resource in load guidance and the
existing day/prescription. This lexical normalization never invents a movement:
resource-only labels or ambiguous remaining names are rejected. In particular,
reject `Pressão de joelho` / `Flexão de perna` independently of an accepting AI review.
Plural forms and load-only qualifiers do not resolve those ambiguous movement
names. Correction instructions must allow replacement of an unidentified
movement; the prohibition on renaming is limited to disguising duplicate exercises.
Persisted unnormalized prefixes require repair before reuse/submission. Apply
normalization to new AI items only, including adaptation candidates, never to
unchanged approved/historical items. Review and persist the same normalized sheet.
Correction feedback identifies the exact item position/name and requires a
recognized movement name, keeping resources in load guidance. Recognizable
names such as `Barra fixa` and `Agachamento com peso corporal` remain allowed;
these bounded ambiguity checks do not create a general exercise catalogue.
The local CPU-only recovery run increases the configured Ollama timeout to
360 seconds after measured 120-second generation timeouts; the configured
provider/model, automatic rejection rules and instructor gate are retained.
The recovery probe found CUDA 12 discovery timing out and falling back to CPU
on the local RTX 4050, while the CUDA 13 library bundled in the same approved
Ollama image detected it successfully. The local Compose profile selects that
bundled library by default through overridable `OLLAMA_LLM_LIBRARY=cuda_v13`;
this does not change the image version, writing model or inference adapter.
The same local writer copied rejected exercise labels in non-thinking mode.
Enable its existing reasoning capability for structured training generation,
automatic assessment, adaptation and authorized draft edits. Preserve the
existing mode for interviews, onboarding extraction, focus extraction and plain
conversation. Consume only the final structured content; never expose, persist
or log private reasoning. Provider/model selection and instructor approval remain
unchanged. Known invalid labels still fail independently of the model's assessment.
This is an automatic quality gate, not a new exercise catalogue, clinical
certification, approval or activation; instructor review remains mandatory.
Acceptance: full-body, targeted and unspecified generation, chat edits and
adaptations all execute the review; known resource-only labels cannot pass even
with a permissive model; corrected content is reviewed before saving; rejection
or review failure leaves saved content unchanged; localized valid sheets are
accepted without requiring full-body coverage; every displayed day is assessed.

The live configured-writer check also exposed expansion of a biceps request
into triceps/shoulders during focus analysis. Before retrieval, `muscle_groups`
must retain muscle/region terms literally present in the request (case, accents
and whitespace are normalized for comparison). Do not replace the client's
terms with anatomical synonyms at this extraction boundary; semantic retrieval
can still match those terms. Invalid focus receives one correction against the
original request; persistent invalid focus fails before retrieval or plan
writing. This validation prevents adding absent labels, but does not infer
negation or anatomically classify arbitrary text.

**Approved interaction amendment (Task 17):** the assistant may proactively
recognize from the authenticated client's own training conversation that a
change could be useful and offer a non-binding draft suggestion. The client
need not formulate a separate adaptation request. The client must explicitly
confirm that suggestion before structured proposal generation, then accept or
reject the generated proposal before instructor review. This does not give the
assistant authority to alter, approve, or activate a plan.

### RF-19 Dynamically adapt training through AI

**Scope:** stated MVP.

Adapt the plan when the client reports through chat that pain, a limitation, or a previous problem is interfering with training.

**Acceptance criteria**

- [ ] **CA-19.1:** in a test scenario where the client reports that a problem interferes with a particular exercise, the AI produces a context-related adaptation.
- [ ] **CA-19.2:** a change approved through the flow results in a new current version.
- [ ] **CA-19.3:** unrelated parts are not improperly removed.
- [ ] **CA-19.4:** the modified plan remains after reauthentication.
- [ ] **CA-19.5:** adaptation generation follows the shared RAG contract and
  persists validated evidence with the retained proposal and instructor draft;
  missing, expired, or unavailable evidence is explicitly qualified. Client
  confirmation requests review only and never approves or activates a plan.

**Consolidation note:** The text requires an approved change but does not detail who approves it or the proposal states. Define this flow under DEC-07; preserve the approved plan as required by RN-16 and RN-17.

**Approved implementation policy (DEC-07/DEC-08/DEC-15, Task 17):** a
client-confirmed AI adaptation is a separate retained structured proposal. It
may add, remove, replace, or adjust a single plan item or several items, while
preserving unrelated content. The AI can suggest a recognized exercise candidate
not already stored, but cannot create a catalog record, approve, activate, or
directly mutate a plan. The client accepts or rejects the proposal; acceptance
only requests instructor review. An instructor may edit, approve, or reject the
proposal. Approval atomically creates a new immutable current version and
supersedes the previous current version. A stale-base proposal is superseded,
not automatically merged. Raw Task 16 chat remains client-only and subject to
its independent 30-day retention; the structured proposal remains in plan
history. Task 21 will later constrain machine-dependent candidates to active
gym-catalog equipment.

### RF-20 Receive an external turnstile-use event

**Scope:** outside the stated MVP.

Provide a REST endpoint for the external service to report a facial-identification result.

**Acceptance criteria**

- [ ] **CA-20.1:** an authenticated, valid request is accepted according to the documented JSON.
- [ ] **CA-20.2:** malformed JSON returns a validation error.
- [ ] **CA-20.3:** the integration does not require the application to implement the turnstile's operating algorithm.
- [ ] **CA-20.4:** a duplicate event with the same identifier does not create duplicate records.

**Consolidation note:** DEC-11 separates the confirmed-passage occupancy
contract from the facial-recognition/release integration. For the latter, a
provider-neutral recognized result may issue one idempotent external release
request; the application does not control turnstile mechanics or infer physical
passage. No payment, enrollment, occupancy, or other authorization policy is
silently added to this recognition decision.

### RF-21 Verify the user's identity and eligibility for access

**Scope:** outside the stated MVP.

Associate the identity reported by the facial service with the client and check whether the account is enabled.

**Acceptance criteria**

- [ ] **CA-21.1:** a known external identity is associated with the corresponding client.
- [ ] **CA-21.2:** an unknown identity produces a denial/unknown-identity decision.
- [ ] **CA-21.3:** an explicitly deactivated client is not returned as enabled.
- [ ] **CA-21.4:** the recognition response must have acceptable precision of at least 95% to be accepted.

**Consolidation note:** DEC-09 defines the 95% minimum as measured system
precision (`TP / (TP + FP)`) on an appropriate representative validation set,
not a universal per-match confidence of `0.95`. The selected provider/model
uses a configurable calibrated threshold; below-threshold results are rejected.
Identification does not replace entry authorization: apply RN-06, RN-35, and
RN-36.

### RF-22 Enter initial biometric data for each client

**Scope:** outside the stated MVP.

An attendant may register a valid facial photo for the client; data from that photo will be used for entry biometrics.

**Acceptance criteria**

- [ ] **CA-22.1:** the photo must pass a previously selected precision threshold.
- [ ] **CA-22.2:** if another photo is registered, it must replace the existing one, and the old photo is then discarded.
- [ ] **CA-22.3:** only employees may change the biometric-photo data associated with each client.

**Consolidation note:** DEC-09 requires a safe replacement transition: enroll
and confirm the replacement, activate it, then revoke the old reference. Raw
captures are temporary and removed after successful enrollment when technically
possible; audit metadata preserves traceability without retaining images or
templates. Employee authorization remains governed by DEC-04 and RN-26/RN-27.

### RF-23 Record entry, exit, and attendance

**Scope:** outside the stated MVP.

Persist access events used as history/attendance.

**Acceptance criteria**

- [ ] **CA-23.1:** a valid entry event creates an entry record.
- [ ] **CA-23.2:** a valid exit event creates an exit record.
- [ ] **CA-23.3:** a repeated event is not counted twice.
- [ ] **CA-23.4:** records include related date/time and client.

**Consolidation note:** Under DEC-11, a confirmed-passage event carries an
opaque external `client_reference`, not the local Client UUID or identifying or
biometric data. The backend resolves it to a valid local Client before
persisting the private ledger relationship required by CA-23.4. Unknown,
invalid, or non-client references are controlled integration failures and do
not create a normal passage event or alter occupancy. The public occupancy API
remains aggregate-only and never exposes the reference, Client relationship, or
individual event records.

### RF-24 Calculate current occupancy

**Scope:** outside the stated MVP.

Derive the number of people currently present from entry and exit events.

**Acceptance criteria**

- [ ] **CA-24.1:** a valid entry increments occupancy once.
- [ ] **CA-24.2:** a valid exit decrements occupancy once.
- [ ] **CA-24.3:** duplicate processing of the same event does not change the total again.
- [ ] **CA-24.4:** the value is not displayed as negative.

**Consolidation note:** DEC-02 normalizes this identifier to RF-24. DEC-10
selects the confirmed-passage ledger as the authoritative client-only count for
one logical zone; RN-37 camera counting is deferred and auxiliary by design.

### RF-25 Display current occupancy

**Scope:** outside the stated MVP.

Show the client the number of people training at the moment.

**Acceptance criteria**

- [ ] **CA-25.1:** the page displays the value calculated by RF-24 for users.
- [ ] **CA-25.2:** after a new event is processed, a new query reflects the new total.
- [ ] **CA-25.3:** the information is legible in a mobile viewport.

**Consolidation note:** CA-25.1 references RF-24, the preceding normalized
requirement. The public meaning is the client-only authoritative count from the
confirmed-passage ledger; see DEC-10 and the occupancy portion of DEC-11.

### RF-26 Record and update billing status

**Scope:** outside the stated MVP.

Maintain basic control of each client's monthly fees/charges.

**Acceptance criteria**

- [ ] **CA-26.1:** an authorized user records the billing period, due date, and status.
- [ ] **CA-26.2:** an update persists.
- [ ] **CA-26.3:** the record is associated with the correct client.

### RF-27 View billing status

**Scope:** outside the stated MVP.

Allow consultation of the basic financial status already recorded.

**Acceptance criteria**

- [ ] **CA-27.1:** an authorized user views the client's records.
- [ ] **CA-27.2:** the client can view their own status when that screen is part of the interface.
- [ ] **CA-27.3:** a client cannot view another person's monthly fees.

### RF-28 Provide an administrative dashboard

**Scope:** outside the stated MVP.

Present an administrative home page consolidating system information.

**Acceptance criteria**

- [ ] **CA-28.1:** only an authorized role can access the dashboard.
- [ ] **CA-28.2:** the page loads data from existing modules, such as monthly, annual, and total billing; the number of subscribing clients and employees; client access history broken down by days/hours; and possibly other indicators.
- [ ] **CA-28.3:** failure of one indicator does not grant unauthorized access or display data from another context.

**Consolidation note:** Financial indicators depend on defining the meaning of invoice, revenue, and profit; see DEC-13.

### RF-29 Display consolidated dashboard indicators

**Scope:** outside the stated MVP.

Make the dashboard useful by showing indicators from already requested functions.

**Acceptance criteria**

- [ ] **CA-29.1:** display at least the number of active clients, attendance history over the weeks, and current occupancy.
- [ ] **CA-29.2:** when the corresponding modules are implemented, a summary of total and monthly profit may be displayed.

**Consolidation note:** The occupancy indicator depends on DEC-10. Profit depends on a calculation definition and data not yet specified, as noted in DEC-13.

### RF-30 Manage the gym class schedule

**Scope:** outside the stated MVP.

Allow an administrative user to record days and times that will later be displayed.

**Acceptance criteria**

- [ ] **CA-30.1:** an administrator creates a class with at least identifying information, date, and time.
- [ ] **CA-30.2:** an occurrence can be changed or removed from the schedule.
- [ ] **CA-30.3:** changes appear in the corresponding public/authenticated view.

**Consolidation note:** The capacity rule RN-25 is conditional. Recurrence, schedule visibility, and any booking flow need definition under DEC-14.

### RF-31 Provide purchase of gym plans

**Scope:** outside the stated MVP.

Allow a user to purchase a gym plan linked to their account. The plan is valid until date X and expires after that time, requiring a new payment to become valid again.

**Acceptance criteria**

- [ ] **CA-31.1:** the client's enabled status must change only if payment was accepted with API confirmation.

**Consolidation note:** Payment confirmation must be related to the other eligibility and entry conditions without removing them. See DEC-05 and DEC-12, as well as RN-22, RN-24, RN-35, and RN-36.

### RF-32 Manage gym equipment

**Scope:** outside the stated MVP.

Allow an administrative user to register, view, update, and deactivate equipment made available by the gym, including its basic information and display image.

**Acceptance criteria**

- [x] **CA-32.1:** an authorized administrative user can register equipment with, at minimum, a name and status;
- [x] **CA-32.2:** the system allows an image to be associated with the equipment;
- [x] **CA-32.3:** registered equipment remains available on a subsequent query;
- [x] **CA-32.4:** an authorized user can change equipment information;
- [x] **CA-32.5:** deactivated equipment no longer appears as available to the client, without requiring deletion of its record.

### RF-33 View available equipment

**Scope:** outside the stated MVP.

Allow visitors or clients to view equipment made available by the gym, together with its basic information and corresponding images.

**Acceptance criteria**

- [x] **CA-33.1:** the interface presents the list of registered active equipment;
- [x] **CA-33.2:** each equipment item shows at least its name and image, when an image has been registered;
- [x] **CA-33.3:** the user can view additional equipment information when registered;
- [x] **CA-33.4:** deactivated equipment does not appear as available;
- [x] **CA-33.5:** the list remains usable on mobile devices.

### 3.1 Approved product-extension requirements

These approved extensions are part of this canonical specification.
`docs/product-extensions.md` retains supporting dependency, privacy, and
unresolved-decision detail.

#### EXT-RF-AI-01 — Conversational AI onboarding

**Scope:** approved MVP product extension. **Related originals:** RF-10–RF-13,
RF-15, RF-18, RN-05, RN-11, RN-23, RN-29, RN-30.

An authenticated client may start or resume a progressive AI conversation that
maps recognized answers into their authoritative structured onboarding. The AI
must leave missing/invalid information incomplete, must not diagnose, must not
bypass validation, and must preserve the secure-link/form route.

Questions may cover objectives, approved physical information, prior experience
where applicable, limitations/complaints, medications, health conditions, and
other fields only when they exist in the approved onboarding schema.

Acceptance: `EXT-CA-AI-01.1` own-client start/resume;
`EXT-CA-AI-01.2` progressive schema-based mapping and persistence;
`EXT-CA-AI-01.3` no invented values or validation bypass;
`EXT-CA-AI-01.4` resumable state; `EXT-CA-AI-01.5` RF-13 completion gates RF-15;
`EXT-CA-AI-01.6` cross-client isolation; `EXT-CA-AI-01.7` no diagnosis and
controlled provider failure; `EXT-CA-AI-01.8` coexistence with link/form.

**Unified assistant presentation:** `/assistente` is the sole client-facing AI
conversation destination. Before the authoritative onboarding is completed, it
shows the progressive onboarding conversation and continues to use the approved
onboarding validation/completion flow. Once completed, the same destination
shows the RF-18 training assistant. The form's “Responder por conversa” action
also targets `/assistente`; the historical onboarding-conversation route
redirects there. This is one user-facing assistant journey, not two client chat
destinations. The onboarding and training conversation records remain distinct
server-side to preserve their approved context, health-data handling, and
retention boundaries; they are not merged or exposed as one message history.

#### EXT-RF-SOC-01 — Controlled progress sharing

**Scope:** approved post-MVP extension. **Related originals:** RF-04, RF-05,
RN-04, RN-05, RN-11, RN-23, RN-28, RN-33.

An authenticated client owns each progress update and selects private or shared
visibility. Only explicitly permitted users may view it; only its author may
modify/delete it. Sensitive account, health, biometric, financial,
authentication, administrative, or presence data is never inserted
automatically.

Acceptance: `EXT-CA-SOC-01.1` authenticated ownership;
`EXT-CA-SOC-01.2` private/shared control; `EXT-CA-SOC-01.3` enforced visibility;
`EXT-CA-SOC-01.4` author-only mutation/deletion; `EXT-CA-SOC-01.5` no automatic
sensitive content; `EXT-CA-SOC-01.6` no unapproved social-network features.

**Approved implementation policy (EXT-DEC-SOC-01):** a new progress update is
private by default. Its author may explicitly make it shared, in which case it
is visible to all active authenticated clients; there are no recipients,
groups, followers, or guest viewers. Private updates remain visible only to the
author, and administrator status alone does not grant access to them.

Administrators may list and moderate shared updates only. They may hide or
restore a shared update, each time supplying a moderation reason; they may not
edit its content or create an update for a client. A hidden update is absent
from other-client feeds, while its author can see that it is hidden and the
reason. The author alone may edit or delete their own update. Deletion removes
the content immediately from every view and leaves only a contentless tombstone
and minimum audit metadata. Active updates are retained until author deletion
or a future approved account-deletion/anonymization policy; hidden updates keep
their content and moderation state so that they can be restored.

Audit evidence for author edits/deletions and administrative hide/restore
actions contains only actor ID, update ID, action, timestamp, and the required
moderation reason. It never duplicates the update content or sensitive domain
data in logs. The UI warns authors not to post health, payment, credential,
attendance, biometric, or presence data. This policy does not add reporting,
comments, likes, direct messages, rankings, or leaderboards.

**Deletion amendment — 2026-09-23:** an administrator may also delete a shared
update, with an optional reason. This leaves a contentless tombstone visible to
no client and retained only while its author account exists. An administrator
may permanently erase a client account: delete the Keycloak identity and every
local record attached to the client, including onboarding, invitations, plans
and history, conversations, adaptations, progress updates/tombstones, account
linkage, and pending identity reconciliation. No audit record is retained, so
the account cannot be reidentified. This irreversible privacy erasure is
distinct from reversible account deactivation.

**Shared-account erasure amendment — 2026-09-27:** when the Client shares an
Account with an Employee, this operation erases only the Client and its owned
data. Preserve the Employee, its history, the shared PersonProfile, Account,
and Keycloak identity. Reconcile away the client role while preserving the
employee's independently active permissions; an inactive Employee is not
reactivated. Pending shared-identity reconciliation remains retryable through
employee management. The full-account erasure behavior above applies only
when no Employee is linked. **Origin:** explicit user decision for the
shared-account integration fixes.

#### EXT-RF-SOC-02 — Social client profile and post interactions

**Scope:** approved post-MVP extension; Task 26 is planned. **Related:**
EXT-RF-SOC-01, EXT-RF-PRES-01, RF-03–RF-05, RN-04, RN-05, RN-11, RN-23,
RN-28, RN-33.

An active authenticated client has an individual social profile visible by
default to other active authenticated clients. The owner always sees their own
profile and is the only actor who sees or changes its visibility switch. The
profile shows the existing client name, an optional owner-editable non-unique
nickname, an optional biography, an owner-managed profile picture,
follower/following information, and the posts permitted for the viewer. Opening
a permitted post shows its like count and comments.

Acceptance: `EXT-CA-SOC-02.1` owner fields and default-on visibility control;
`EXT-CA-SOC-02.2` validated client-owned image lifecycle;
`EXT-CA-SOC-02.3` authenticated cross-client visibility and minimized social
projection; `EXT-CA-SOC-02.4` follow graph and lists;
`EXT-CA-SOC-02.5` newest-first viewer-appropriate post history;
`EXT-CA-SOC-02.6` unique likes and author-owned comments;
`EXT-CA-SOC-02.7` approved administrator moderation;
`EXT-CA-SOC-02.8` complete account-erasure coverage and sensitive-data
exclusion; `EXT-CA-SOC-02.9` independent profile-presence consent;
`EXT-CA-SOC-02.10` future-feed boundary without current feed implementation.

**Approved implementation policy (EXT-DEC-SOC-02):** names and nicknames are
presentation only; the Client UUID remains canonical. Nicknames are optional,
non-unique, plain text, owner-editable, and limited to 40 characters. Biography
is optional plain text up to 160 characters. Profile images are JPEG, PNG, or
WebP up to 5 MiB, validated by content, normalized with metadata removed, and
stored as bytes in a dedicated client-owned PostgreSQL record.
Replacement/removal deletes prior bytes.

Visibility defaults on but never grants anonymous access. When off, another
client cannot read the profile, its profile post collection, or follower lists;
follow edges are retained. Per-post private/shared visibility remains governed
by EXT-DEC-SOC-01, so switching the profile off does not silently rewrite or
unshare posts. The owner sees their private/shared posts and moderation state;
an allowed other-client profile view shows only shared, non-hidden posts.
Profile post order is newest-first and deleted posts are omitted.

Following is unilateral, allows no self-follow or duplicate edge, and has no
request/approval flow. Likes are limited to one per active client per accessible
shared, non-hidden post. Permitted clients may add plain-text comments up to the
existing 2,000-character post-content ceiling to such posts; only the comment
author may delete it through the client API, and the post author gains no extra
deletion authority. Administrators may hide/restore
shared comments and biography/profile-image content with a required reason and
may delete them with an optional reason; administrators never edit client
content or change profile visibility.

Existing post moderation/tombstones remain authoritative. Post deletion removes
its likes/comments. Full account erasure removes the profile, image bytes,
follow edges in both directions, likes, comments, posts/tombstones, and related
audit data. Other-client projections exclude e-mail, internal IDs, health,
training, attendance history, biometric, payment, credential, and administrative
data. EXT-DEC-PRES-01 independently controls whether the derived current-presence
tag appears. Task 26 creates no feed, recommendations, messaging, notifications,
rankings, leaderboards, blocks, private follow requests, or public profiles.

#### EXT-RF-SOC-03 — Authenticated chronological social feed

**Scope:** approved post-MVP extension; Task 27 is planned. **Related:**
EXT-RF-SOC-01, EXT-RF-SOC-02, EXT-RF-LANG-01, RF-03–RF-05, RN-04, RN-05,
RN-11, RN-23, RN-28, RN-33, RNF02–RNF04.

The authenticated client “Progresso” destination is a chronological social
feed of shared ProgressUpdate posts. Clients compose their own
private-by-default or explicitly shared posts, optionally with images, and open
a post to like it and read or create comments. The feature remains limited to active
authenticated clients and does not create a public guest surface.

Acceptance: `EXT-CA-SOC-03.1` stable newest-first cursor feed of permitted
shared posts; `EXT-CA-SOC-03.2` accessible top composer and scroll-triggered
compact return action, with the resulting owner-attached ProgressUpdate also
appearing in the permitted profile history; `EXT-CA-SOC-03.3` validated
lifecycle for up to four post images and one comment image;
`EXT-CA-SOC-03.4` always-visible like and comment counts plus authorized
author-profile navigation;
`EXT-CA-SOC-03.5` newest-first comments with author summary and image-only
comment support; `EXT-CA-SOC-03.6` author-only text/attachment editing with an
“editado” indication; `EXT-CA-SOC-03.7` private-profile/shared-post and
shared-to-private transition policy; `EXT-CA-SOC-03.8` aggregate moderation,
deletion, audit minimization, and account erasure; `EXT-CA-SOC-03.9` responsive,
accessible, resilient infinite loading; `EXT-CA-SOC-03.10` no ranking,
recommendations, replies, messaging, notifications, blocks, or guest access.

**Approved implementation policy (EXT-DEC-SOC-03):** “public” in this feature
means the existing `shared` visibility: available to active authenticated
clients only. New posts remain private by default and require an explicit
choice to become shared. The feed contains shared, non-deleted,
moderation-visible posts ordered by `(created_at DESC, id DESC)` through an
opaque cursor. It has no algorithmic ordering, ranking, recommendation, or
follow-based filtering.

ProgressUpdate remains the only post aggregate. Post and comment text is
trimmed plain text up to 2,000 characters. A post or comment must contain text
or at least one image, so image-only posts and image-only comments are allowed.
A post accepts at most four images and a comment at most one. Each image accepts
JPEG, PNG, or WebP input up to 5 MiB, is decoded and validated by content,
rejects animated/malformed/unsupported input, has orientation normalized,
metadata removed, dimensions bounded within 1024×1024 while preserving aspect
ratio, and is safely re-encoded into a dedicated PostgreSQL media record. Media
bytes are never base64 JSON, an external URL, or a host filesystem path and are
served only through authorized endpoints.

Authors may edit their own post/comment text and replace or remove attachments.
Replacement/removal deletes superseded bytes in the same transaction. A
client-facing content or attachment change sets `edited_at`; the UI shows
“editado” without exposing edit history. A shared post with any retained,
non-deleted comment cannot become private. Likes do not block that transition:
if a liked post becomes private, likes remain persisted but inaccessible for
cross-client reads or interaction and become visible again if the post is
reshared. Private and hidden posts reject new likes/comments.

Profile visibility and post visibility remain independent. A shared post from
a hidden/private social profile remains eligible for the feed. Its author link
opens a private-profile state exposing only the presentation username
(nickname when present, otherwise existing client name) and the permitted
profile picture or fallback avatar; biography, graph, presence, and profile
post history remain hidden. This is not anonymous/public profile access.

Feed cards always show author, time, permitted text/media, like count, and
comment count without hover. Post detail orders visible comments newest-first,
superseding Task 26's chronological comment presentation only for the current
product behavior. There are no replies or reply relationships. Administrators
may hide/restore with a required reason or delete with an optional reason only
the whole shared post or whole shared comment, including its attachments; they
never edit user content. Post deletion removes attached images, likes, and
comments/images and leaves only the already-approved contentless tombstone and
minimum audit metadata. Comment deletion removes its text/image from client
views. Full account erasure removes all authored/received social relationships,
media bytes, posts/tombstones, comments, likes, and related audit metadata.

**Account-privacy amendment — 2026-09-26:** This supersedes the per-post
private/shared composer choice and independent-profile-visibility behavior for
the authenticated social feature. A public account's active posts are shared to
active authenticated clients; a private account's active posts are visible only
to its owner and accepted followers. Changing account privacy updates every
active authored post immediately. The composer has no visibility selector. A
non-follower may submit one pending follow request to a private account; only
its owner can list, accept, or reject requests. Accepted followers may read the
private account, its active non-hidden posts, and authorized media and use
existing permitted interactions. Anonymous/guest access remains forbidden.

#### EXT-RF-EQP-01 — Equipment quantity by logical type/model

**Scope:** approved post-MVP extension. **Related originals:** RF-32, RF-33,
RN-04, RN-33.

Administrative equipment management and client/visitor consultation must
support the total count of active units for an approved logical type/model,
alongside name, optional image, and additional RF-33 information.

Acceptance: `EXT-CA-EQP-01.1` authorized grouping management;
`EXT-CA-EQP-01.2` active total displayed; `EXT-CA-EQP-01.3` deactivation updates
the count while preserving required history; `EXT-CA-EQP-01.4` total units are
never represented as real-time free/available units.

**Equipment administration and UI amendment — 2026-09-27:** The owner approved
an integrated model-and-units registration flow, bulk unit creation with an
optional identifier prefix, equipment search/filtering and a dedicated details
workspace, image preview/error feedback, per-field pt-BR validation, duplicate
submission prevention, deactivation confirmation and editable unit labels.
Administrator units show inventory and operational states separately. Redesign
administrator, instructor and public/client equipment surfaces using the
existing visual system and existing role boundaries. Model creation and its
initial units commit atomically. Bulk creation accepts 1–100 units, gives each
an individual identity and avoids generated-label collisions within its model.
Counts remain derived from units. Instructor search applies before pagination.
Existing historical plans and the operational-state permissions are preserved.
Optional brand, manufacturer model and free-text category belong to the model;
optional gym location and serial number belong to each physical unit. All five
fields are administrator-only and excluded from public/client/instructor/AI
projections. No serial-number uniqueness, maintenance or tracking workflow is
introduced. Direct image upload is approved alongside existing links: reuse the
bounded JPEG/PNG/WebP 5 MiB decoder, strip metadata, normalize to at most 1024×1024
and store ordinary equipment images separately from biometrics in PostgreSQL.
Only administrators mutate photos; public images require an active model.
Replacing the photo/link removes the superseded source. If photo upload fails
after atomic model-and-units creation, show the saved equipment and offer photo
retry without creating the model or units again.

#### EXT-RF-PRES-01 — Opt-in visible presence

**Scope:** approved post-MVP extension; Task 22 and `EXT-DEC-PRES-01` are complete.
**Related originals:** RF-23–RF-25, RN-04, RN-05, RN-10, RN-11, RN-23, RN-34,
RN-37.

Profile presence is a separate opt-in client feature, not anonymous occupancy
and not inferred from camera/biometric data. It is a current-status tag only on
an individual profile, never a directory or list. A non-opted-in client has no
presence tag, and the view exposes no additional profile data.

Acceptance: `EXT-CA-PRES-01.1` default-off opt-in;
`EXT-CA-PRES-01.2` non-consenting clients excluded; `EXT-CA-PRES-01.3` preference
lifecycle enforced; `EXT-CA-PRES-01.4` sensitive data excluded;
`EXT-CA-PRES-01.5` anonymous count remains independent;
`EXT-CA-PRES-01.6` staff visibility does not imply client/public visibility.

#### EXT-RF-INST-01 — Instructor authenticated area and read-only feed

**Scope:** approved post-MVP extension. **Related:** RF-04, RF-05, RF-07,
RF-08, EXT-RF-SOC-02, EXT-RF-SOC-03, EXT-RF-LANG-01, RN-04, RN-05,
RN-11, RN-23, RN-31, RNF02–RNF04.

An active locally linked Employee with the `instructor` specialization and an
authenticated Keycloak `instructor` role has a dedicated SPA area. Its ordered
navigation is Feed, Planos pendentes, Meus planos, Todos os planos, Clientes,
Equipamentos, and Perfil. Feed is the post-login default and there is no
dashboard/home destination. Perfil is a clearly bounded future-feature state,
not an invented instructor social profile.

**Dual-role navigation amendment — 2026-09-27:** a session with both active
client and instructor roles exposes a switch in each area's sidebar and mobile
drawer, outside the ordered destinations. It labels the current area and opens
the other area without logging out or modifying permissions. Instructor entry
remains Feed; explicit client entry uses the existing completed-onboarding
Feed / unfinished-onboarding entry rule. Single-role sessions have no switch.
This is navigation only: it does not change either area's social policies or
grant access based on a browser-selected area. **Origin:** explicit user request
for a design-system-consistent area switch.

The instructor feed reuses the existing chronological social-feed projection
and presentation. It contains only moderation-visible posts belonging to
public client profiles. Private-profile posts remain unavailable because an
instructor has no client follow identity. The instructor may read the feed and
permitted post detail, but may not create, edit, like, unlike, comment, follow,
or act through a client social identity.

Acceptance: `EXT-CA-INST-01.1` local active-employee and Keycloak-role
authorization; `EXT-CA-INST-01.2` exact responsive navigation and default Feed
route; `EXT-CA-INST-01.3` reuse of the public-profile-only feed policy;
`EXT-CA-INST-01.4` read-only post detail and absence/denial of every social
mutation; `EXT-CA-INST-01.5` bounded Perfil placeholder without social-profile
creation; `EXT-CA-INST-01.6` direct API denial for inactive or unauthorized
identities.

#### EXT-RF-INST-02 — Single-draft instructor review and responsibility

**Scope:** approved post-MVP extension. **Related:** RF-15–RF-19, RF-07,
RF-08, RN-12–RN-19, RN-29–RN-33, DEC-07, DEC-15.

Every client has at most one editable training-plan draft (`proposal`) across
initial AI generation, instructor manual creation, editing a current plan, and
client-accepted AI adaptation. A retained adaptation source/history record may
remain, but it is not a second instructor-editable draft. Moving an adaptation
to instructor review must use the sole draft boundary and must never silently
replace another draft.

Planos pendentes lists every current draft requiring instructor review,
regardless of instructor assignment. Each result identifies the client, draft
origin, creation/update information, and the responsible instructor for an
existing current plan when applicable. Any instructor may save a concurrency-
checked edit without activation, approve directly, or explicitly approve after
editing. Approval and activation form one atomic instructor action: the draft
becomes current, the prior current version becomes immutable history, the
approving Employee becomes responsible, and the approval timestamp is recorded.
The first successful stale-state-sensitive write wins; later stale writes return
a conflict requiring reload.

For a submitted standalone exercise sheet, instructor review also offers
appending selected exercises to the same client's current plan. The instructor sees
both the suggestion and the current plan before choosing. This reuses the sole
draft as the next version of the current plan, preserves current exercises and
their order, and appends only the explicitly selected generated exercises in
their original order. Empty, duplicate and invalid selections are rejected.
Preparation
does not activate the draft; explicit instructor approval activates the combined
version and preserves immutable history and responsibility. Both the displayed
draft revision and current-version ID/revision must match. Cross-client, stale,
unsubmitted and already-combined/adaptation drafts cannot use this action.
Manual combination invalidates unvalidated whole-plan citation applicability.
This is **EXT-CA-INST-02.9**, approved by the owner's 2026-10-18 clarification.

The client current-plan view displays the responsible instructor's current
first name and surname and the approval date. Historical versions retain their
original immutable instructor attribution even if that employee is later
renamed or deactivated; therefore historical attribution must not depend only
on a mutable live display name.

Acceptance: `EXT-CA-INST-02.1` one cross-source draft per client;
`EXT-CA-INST-02.2` complete pending list and required metadata;
`EXT-CA-INST-02.3` save-edit does not activate;
`EXT-CA-INST-02.4` direct and edit-then-approve atomically create the new
current version; `EXT-CA-INST-02.5` responsible instructor and date appear to
the client; `EXT-CA-INST-02.6` immutable historical attribution;
`EXT-CA-INST-02.7` stale concurrent writes cannot overwrite newer state;
`EXT-CA-INST-02.8` backend instructor authorization and cross-client data
minimization.

#### EXT-RF-INST-03 — Instructor plan collections, history, and authoring

**Scope:** approved post-MVP extension. **Related:** EXT-RF-INST-02, RF-16,
RF-17, RF-19, RN-14, RN-16–RN-19, RN-31–RN-33.

Meus planos lists current plans for which the authenticated instructor is the
responsible Employee. Todos os planos lists all current plans and supports
combinable client-name search, responsible-instructor filtering, and approval
date/date-range filtering. Results identify client, responsible instructor,
latest approval date, and current status. Any instructor may open and edit any
current plan through the sole-draft workflow and may inspect immutable approved
history.

Approval date/date-range filters interpret calendar dates in
`America/Sao_Paulo`, with both selected dates inclusive. A single-date filter
covers that entire local day; a range covers the start date through the end
date, excluding the following local midnight. **Origin:** explicit user
timezone decision for Task 32.

Editing current content never changes the current or historical version in
place. If a draft already exists, the UI must identify it and obtain explicit
confirmation before discarding it and cloning the current plan; cancellation
preserves the existing draft. An instructor may manually create the first draft
only when the client has neither a current plan nor another draft. Creation and
activation remain separate; only explicit approval activates it.

Acceptance: `EXT-CA-INST-03.1` correctly scoped Meus planos;
`EXT-CA-INST-03.2` complete Todos os planos with combinable filters;
`EXT-CA-INST-03.3` current/history detail with read-only history;
`EXT-CA-INST-03.4` approved-plan editing through a new sole draft;
`EXT-CA-INST-03.5` explicit existing-draft discard confirmation;
`EXT-CA-INST-03.6` first-plan manual draft and separate approval;
`EXT-CA-INST-03.7` direct API authorization and concurrency enforcement.

#### EXT-RF-INST-04 — Instructor client workspace and onboarding

**Scope:** approved post-MVP extension. **Related:** RF-02, RF-11–RF-15,
EXT-RF-INST-02, EXT-RF-INST-03, RN-04, RN-05, RN-11, RN-23, RN-31,
DEC-06, DEC-18.

Any instructor may search active clients by partial, case-insensitive name,
with accent-insensitive matching where supported by the approved PostgreSQL
deployment, ordered alphabetically. Combinable filters cover onboarding
(Todos, Concluído, Não concluído), training (Todos, Sem plano, Pendente de
aprovação, Plano ativo), and responsible instructor (Todos, Sem instrutor, Eu,
Instrutor específico). There is no instructor filter for client account-active
state and no separate “Somente rascunho” state.

Results and the client workspace expose only the name and onboarding/training
state needed for the instructor's function, current responsible instructor,
sole draft when present, and current plan when present. Contextual actions allow
continuing/completing unfinished onboarding, editing completed onboarding in
place, creating the first manual draft when eligible, and opening the draft or
current plan. Normal onboarding validation remains authoritative. Instructor
reads and writes are attributable through minimized audit metadata containing
actor, target, action, timestamp, outcome, and changed field names, never health
values. Admin role alone, attendants, and ordinary employees receive no access.

Acceptance: `EXT-CA-INST-04.1` active-client name search and ordering;
`EXT-CA-INST-04.2` exact combinable filters without redundant draft state;
`EXT-CA-INST-04.3` minimized workspace status and contextual actions;
`EXT-CA-INST-04.4` continuation and valid completion of unfinished onboarding;
`EXT-CA-INST-04.5` valid in-place update of completed onboarding;
`EXT-CA-INST-04.6` need-to-know authorization and cross-client isolation;
`EXT-CA-INST-04.7` non-sensitive instructor attribution.

#### EXT-RF-INST-05 — Instructor equipment operational state

**Scope:** approved post-MVP extension. **Related:** RF-32, RF-33,
EXT-RF-EQP-01, RF-15, RF-19, RN-04, RN-20, RN-33,
EXT-DEC-EQP-01.

EquipmentUnit gains an operational state independent from its inventory-active
state, limited to `operational` and `out_of_order`. Instructors may view active
equipment models and their physical units and change only this operational
state. They may not create, edit, activate/deactivate, or delete models/units or
change labels, descriptions, images, or other inventory metadata.

An active EquipmentModel is usable for new training-plan content only when it
has at least one unit that is both inventory-active and operational. If every
active unit is out of order, the model is unusable for new initial-generation,
adaptation, and instructor-authoring/review choices. Existing current and
historical plans retain their references and are never rewritten. Operational
does not mean currently free, and no occupancy, reservation, telemetry, or
real-time availability semantics are added.

Acceptance: `EXT-CA-INST-05.1` separate persisted operational state;
`EXT-CA-INST-05.2` instructor read and operational/out-of-order mutation only;
`EXT-CA-INST-05.3` admin inventory behavior remains distinct;
`EXT-CA-INST-05.4` training usability requires an active operational unit;
`EXT-CA-INST-05.5` retained plans/history are unchanged;
`EXT-CA-INST-05.6` no live-availability meaning or unauthorized mutation.

#### EXT-RF-LANG-01 — Portuguese user-facing application

**Scope:** approved cross-cutting extension for existing, MVP, and post-MVP UI.
**Related originals:** RNF02, RNF03, RF-04, RF-10, RF-18.

Application-controlled text shown to users in public, client, and
administrative frontend areas must be in Brazilian Portuguese (`pt-BR`). This
includes navigation, actions, form labels/help, validation, loading, empty,
success, error and authorization states, dialogs, notifications, and accessible
names. In-app AI onboarding and training-chat responses must address clients in
Portuguese. Established technical or fitness terms commonly used in English,
such as “bulking,” may remain in English when that is clearer to users.
User-authored content, proper names, technical identifiers, API contracts,
implementation documentation, and Codex task prompts are not translated by
this requirement.

Acceptance: `EXT-CA-LANG-01.1` application-controlled public/client/admin UI
copy and accessible names are in `pt-BR`, including failure and empty states;
`EXT-CA-LANG-01.2` in-app AI responses and client-facing generated guidance are
in Portuguese without changing structured-data validation or safety rules;
`EXT-CA-LANG-01.3` user-facing dates, times, numbers, and currency values use
appropriate `pt-BR` formatting where displayed;
`EXT-CA-LANG-01.4` login and first-access screens displayed through Keycloak
are in Portuguese, without changing the approved authentication architecture;
`EXT-CA-LANG-01.5` representative phone, tablet, and desktop flows have no
unintended English application copy. Familiar gym/technical terms are allowed.

EXT-RF-SOC-03 additionally approves only its authenticated chronological feed
and bounded post/comment media lifecycle. No extension approves
friend/private-follow requests, replies, blocks, recommendations, messages,
notifications, algorithmic rankings, leaderboards, public guest profiles, or
live equipment-use tracking.

### 3.2 Client-facing training and assistant interpretation (DEC-19)

RF-16 is implemented as a personal, mobile-usable area where the authenticated
client views only their current training-plan version, its exercises, and the
relevant instructions contained in that approved version. A browser-supplied
client ID cannot select the plan.

RF-18/RF-19 remain client-facing after onboarding. When functionally necessary
and authorized, the assistant may receive only that authenticated client's
structured onboarding, current approved plan, permitted version/history
context, and client-visible exercise/equipment information already implemented
by an approved module. Missing modules do not authorize invented context.
Suggestions and chat responses do not become the current plan: approval,
versioning, safety, professional responsibility, manual fallback, and history
rules in RF-17/RF-19 and RN-12–RN-19/RN-31 continue to govern changes.

#### EXT-RF-FACE-01 — Controlled local facial-access pilot

**Status:** approved for implementation, not yet implemented. **Scope:** owner-only
local test; RF-01/03/07/08 and RF-20–RF-25. **Decision:** EXT-DEC-FACE-01.

This later explicit policy amends DEC-04/05/09/10/11/17/18 only for the pilot:

- Administrators enroll, replace/revoke faces, operate the access panel and view
  safe operational history. No instructor permission or new attendant workflow.
- Valid biometric enrollment is mandatory before either new Client or Employee
  registration completes. One separately protected enrollment belongs to the
  shared person and is reused when adding a second role. Bootstrap administration
  needs no scan. Ordinary login remains independent of biometric readiness.
- Capture live webcam images only on explicit button presses. Reject zero/multiple
  faces, unknown/ambiguous or below-threshold matches. At most one additional
  capture per failed recognition attempt. No liveness protection is claimed.
- Use local Docker CompreFace at no software/model fee. Provider enrollment images
  are retained locally until replacement, revocation or person deletion; only
  opaque references/lifecycle metadata belong in the application database.
  Attempt captures are transient; no biometric material in logs/AI/social/APIs.
- Safe replacement activates a successful replacement before deleting the old
  subject. Staged/revoked/superseded references never authorize. Cleanup survives
  failures. Shared-role removal preserves the remaining person's enrollment;
  full erasure removes local/provider material and related history.
- Entry requires a recognized, enrolled active Client currently outside. This is
  an explicit pilot-only RN-35/RN-36 exception: no membership/payment/modality/
  access-allowance implementation. Exit permits a recognized Client currently
  inside regardless of Client/account activity. Deactivation retains enrollment
  for exit; explicit revocation denies recognition use immediately.
- Authorization produces one idempotent recorded/displayed simulated release,
  never an external turnstile call. Only explicit admin confirmation of simulated
  passage changes state/count. Reject inconsistent transitions; protect concurrent
  confirmation/correction with server-side transaction and revision checks.
- Admin state corrections require a reason, append audit and ledger adjustments,
  and update per-client state atomically; they never pretend recognition/release.
- Simulated events retain internal provenance and update the existing aggregate
  count with its existing 60-second heartbeat/120-second freshness behavior.
  No extra simulation label is added to the occupancy page. The test panel is
  explicitly simulated. Named presence remains separately consented and must
  respect corrections, not infer presence from recognition.
- Add enrollment to existing admin person forms and one Acesso facial page with
  test panel, recent events, corrections and controlled failures. All UI pt-BR.
- No agreement/consent UI for the owner-only controlled experiment. No enrolling
  others, staff tracking/attendance, cloud recognition or actual gate control.
- Keep event/audit history until test reset/person deletion. The authorized reset
  removes local test identities from Keycloak/database after new registration is
  usable, preserving bootstrap admin/service access and unrelated gym configuration.
- CA-21.4's representative >=95% precision remains unverified; a self-test does
  not pass it. Full eligibility, hardware, liveness/privacy and representative
  quality validation remain gates for any later real/additional-person rollout.

**Acceptance criteria (definition of pilot completion):**

| ID | Required evidence |
| --- | --- |
| FACE-CA-01 | Both registration APIs/UI reject missing/invalid enrollment; successful scan enables registration; failed enrollment creates no partial Client/Employee and abandoned provider material is cleaned. |
| FACE-CA-02 | Same-person second-role creation reuses enrollment; conflicting CPF/e-mail remains rejected; staff-only scans cannot enter/count as clients. |
| FACE-CA-03 | Only admin may operate new endpoints; direct client/instructor/anonymous calls fail; cross-operator sessions/attempts cannot be consumed. |
| FACE-CA-04 | Capture is live, button-triggered, bounded and single-face; no background recognition; camera tracks stop when closing. |
| FACE-CA-05 | Failed replacement preserves old enrollment; successful replacement disables old reference; revocation immediately denies use and cleanup resumes after restart. |
| FACE-CA-06 | Entry requires a valid recognized active Client outside; exit accepts recognized inside Client despite deactivation; unknown/ambiguous/low-score results never authorize. |
| FACE-CA-07 | Successful authorization produces one persisted/displayed simulated release; no actual turnstile call; stable trigger locator and adapter contract are documented. |
| FACE-CA-08 | Scan/release without confirmation leaves count unchanged; one timely confirmation transitions state/count exactly once; stale, repeated and concurrent transitions do not double-count. |
| FACE-CA-09 | Reasoned admin correction updates client state and count atomically with audit; no forged match/release; repeated/no-op corrections do not drift. |
| FACE-CA-10 | Existing occupancy page shows the updated count with normal stale handling and no new simulation label; no identities leak to aggregate views. |
| FACE-CA-11 | Local-only provider behavior, no paid dependency, no browser API key, no ordinary image/template endpoint, no sensitive logging or AI context; attempt captures transient. |
| FACE-CA-12 | Shared-role removal preserves needed enrollment; full person erasure removes associated local/provider data and leaves coherent count; reset verified in both Keycloak and database. |
| FACE-CA-13 | Provider/camera/database failure and restarts follow section 8; bounded retries and cleanup; unrelated app functions remain usable. |
| FACE-CA-14 | Admin forms/page work at 360×800, 768×1024 and 1366×768 with keyboard focus, understandable feedback and no horizontal page overflow. |
| FACE-CA-15 | No agreement workflow, staff tracking/attendance, attendant provisioning, continuous recognition, real release, or membership billing introduced. |
| FACE-CA-16 | Record actual model/threshold, latency and self-test evidence without claiming measured population precision or liveness. Real-hardware quality gate remains unverified. |

Detailed bounded API/state/transaction contracts, technical defaults, failure
behavior, owner-only verification and dependency order are recorded in
[the facial-access specification](facial-access-specification.md), sections 3–12.
They support this canonical policy; conflicts require a human decision.

## 4 Non-functional requirements

The six RNFs below preserve all their criteria. DEC-16 defines their approved
personal-use measurement protocol; it does not impose commercial-scale load,
redundancy, or a production uptime SLA.

### 4.0.1 Approved RNF measurement protocol (DEC-16)

The system is intended for personal use. Formal MVP verification uses the
following bounded conditions:

- **Reference data and load:** use approximately 50 synthetic clients with
  representative onboarding, training, and conversation history. Normal load
  is one active user; the burst check issues three simultaneous requests.
- **Performance and timeouts:** execute each representative common internal
  operation ten times. At least nine executions must complete within two
  seconds. Operations that depend on external services must show visible
  processing feedback within 200 milliseconds and must end with either a valid
  result or a controlled error under the timeout/retry policy approved for that
  adapter. OpenAI retains its ten-second-per-attempt timeout and one retry;
  Ollama retains its separately configurable local timeout.
- **Responsive behavior:** verify the critical journey at 360×800 smartphone,
  768×1024 tablet, and 1366×768 computer viewports. Controls and content must
  remain usable, and the smartphone viewport must not require horizontal
  scrolling.
- **Usability:** the intended user must complete the documented client,
  instructor, and administrator critical journeys from a checklist without
  consulting source code or receiving step-by-step assistance. A blocked task
  fails the check; confusing but completable steps are recorded as findings.
- **Accessibility:** critical journeys must support keyboard navigation,
  visible focus, readable contrast, and accessible labels. Automated checks
  must report no critical accessibility violations.
- **Availability and recovery:** while the personal host, network, and required
  infrastructure are running, execute an eight-hour local soak with a core
  health check every minute and no unexplained core-service outage. Planned
  maintenance and host/network downtime are excluded. After a normal stack
  restart, core functions must recover within five minutes without data loss or
  manual database repair. High availability and redundant infrastructure are
  not required.
- **Failure isolation:** simulated AI and e-mail failures must return controlled
  errors and must not make independent internal functions unavailable or
  corrupt authoritative data.
- **Maintainability and integration:** the full affected automated suite must
  pass; significant changed behavior requires regression coverage; business
  rules remain in service/domain modules; and fake compatible adapters must
  demonstrate that provider-specific contracts and failures do not leak into
  domain or public API contracts.

Task 19 must record the environment, commands, results, and evidence for every
RNF criterion. These conditions approve formal MVP verification only; a later
deployment with broader users or infrastructure requires a new measurement
decision.

### RNF01 Performance

The system must respond quickly to operations performed by users.

**Acceptance criteria**

- [ ] **CA-RNF01.1:** common query, navigation, and write operations must respond to the user within 2 seconds under normal usage conditions.
- [ ] **CA-RNF01.2:** operations depending on external services or inherently longer processing must indicate that processing is under way, without making the interface appear frozen.
- [ ] **CA-RNF01.3:** if an external service is unavailable or slow, the system must return a controlled error message without blocking the operation indefinitely.

### RNF02 Usability

The system must have a clean, intuitive, easy-to-use interface requiring little training.

**Acceptance criteria**

- [ ] **CA-RNF02.1:** functions intended for each role must be accessible through understandable navigation and labels, without requiring technical knowledge of the system.
- [ ] **CA-RNF02.2:** forms must clearly indicate required fields, input errors, and available actions.
- [ ] **CA-RNF02.3:** a representative user must be able to perform their role's main tasks without specific training beyond initial guidance.

### RNF03 Responsiveness

The interface must adapt to smartphones, tablets, and computers, prioritizing a good mobile experience.

**Acceptance criteria**

- [ ] **CA-RNF03.1:** main screens must remain usable on smartphones, tablets, and computers without overlapping or clipped content.
- [ ] **CA-RNF03.2:** menus, buttons, forms, and interactive elements must remain accessible and usable on small screens.
- [ ] **CA-RNF03.3:** main content must not require horizontal scrolling on smartphones at the resolutions supported by the project.

### RNF04 Maintainability

The system must be developed to require little maintenance, favoring code organization, modularity, ease of evolution, and ease of fixing problems.

**Acceptance criteria**

- [ ] **CA-RNF04.1:** changes in one module must not require widespread changes in other modules when there is no necessary functional dependency.
- [ ] **CA-RNF04.2:** system components must have well-defined responsibilities, avoiding duplicated logic and unnecessary coupling.
- [ ] **CA-RNF04.3:** significant changes must have sufficient related tests to detect regressions in affected functions.

### RNF05 Availability

The system must be available for users 24 hours a day.

**Acceptance criteria**

- [ ] **CA-RNF05.1:** core services must remain continuously available except during scheduled maintenance.
- [ ] **CA-RNF05.2:** failures of an external service, such as an AI or e-mail provider, must not make internal functions unavailable if they do not directly depend on that service.
- [ ] **CA-RNF05.3:** when an external component is unavailable, the system must report the failure in a controlled way and allow independent operations to continue.

### RNF06 Integration

External-system integrations must be decoupled so that external services can be replaced or updated without widespread system changes.

**Acceptance criteria**

- [ ] **CA-RNF06.1:** communication with each external service must use a defined interface or integration layer, avoiding direct dependencies scattered across the application domain.
- [ ] **CA-RNF06.2:** replacing a compatible external provider must require changes concentrated in its integration layer, without widespread changes to business rules.
- [ ] **CA-RNF06.3:** failures or contract changes in an external service must be handled by the integration layer and must not expose the provider's internals to other layers.

### 4.1 Cross-cutting constraints in other sections

Quality and security constraints also appear within business rules and functional criteria. They remain applicable under their original IDs; this table only helps locate them.

| Topic | References and applicable condition |
| --- | --- |
| Authentication and authorization | RF-04, RF-05, and RN-02 through RN-05: control sessions, roles, and access in the API as well. |
| Privacy and segregation | RF-12, RF-18, RN-10, RN-11, RN-23, RN-28, RN-29, and RN-34: limit access to and exposure of health data, biometrics, logs, exports, and AI context. |
| Integrity and history | RF-17, RF-20, RF-23, RF-24, RN-01, RN-18, RN-20, and RN-33: maintain identity, history, relationships, and duplicate handling. |
| Audit and traceability | RN-03, RN-09, RN-21, RN-26, RN-27, RN-31, and RN-32: record responsible people, reasons, notices, and dates consistently. |
| Continuity during external failures | RN-08, RN-19, RNF01, RNF05, and RNF06: provide alternatives for facial recognition, manual training-plan creation, and controlled failure handling. |
| Biometric quality | CA-21.4, CA-22.1, and RN-07: apply DEC-09's >=95% measured configured-system precision and provider/model-calibrated threshold. |
| Deployment | CA-06.4 and section 6: cover SMTP container isolation, Docker Compose, and the firewall indication. |

## 5 Business rules

All 37 business rules are preserved below, including those that also describe functions or non-functional constraints. Conditional rules retain their conditions of application.

| ID | Business rule | Indicated application |
| --- | --- | --- |
| RN-01 | Each person must have a unique identity in the system according to the identifier defined by the project. | Registration |
| RN-02 | An inactive user cannot authenticate normally. | Authentication |
| RN-03 | A deactivated employee loses operational permissions, but their history remains associated with them. | Employees/Audit |
| RN-04 | Every protected operation must consider the authenticated user's role/permission. | Security |
| RN-05 | A client may view only data belonging to their own context, except for specifically shared functions. | Privacy |
| RN-06 | Facial recognition identifies/verifies the person; entry authorization must occur in a separate step. | Biometrics/Access |
| RN-07 | A facial match below the configured threshold must never be automatically converted into a positive identification. | Biometrics |
| RN-08 | An alternative flow must exist for facial-recognition failure. | Biometrics |
| RN-09 | Every manual release that bypasses a normal access rule must record the responsible person and reason. | Access control |
| RN-10 | Biometric data must be handled separately from ordinary registration data. | LGPD |
| RN-11 | Recorded medical information, injuries, or restrictions must not be available to employees without a functional need. | LGPD |
| RN-12 | AI-generated suggestions may be viewed by instructor employees to assess their validity. | AI |
| RN-13 | AI proposals must incorporate relevant client-reported health information. Under the approved Task 14 DEC-07 interpretation, this does not automatically block proposal generation; an instructor must review before approval or activation. | AI/Training |
| RN-14 | The instructor must be able to modify a suggestion in full. | AI/Training |
| RN-15 | Client restrictions take precedence over optimizations suggested by AI. | AI/Training |
| RN-16 | AI must not silently modify an already approved training plan. | AI/Training |
| RN-17 | An AI-proposed change to an existing plan must result in a new proposal/version. | AI/Training |
| RN-18 | Previously completed workouts cannot be modified retroactively when the current plan is updated. | History |
| RN-19 | Failure of the AI service must not prevent the instructor from creating a training plan manually. | Functional availability |
| RN-20 | An inactive exercise may remain in historical plans but must not normally be selectable for new prescriptions. | Exercises |
| RN-21 | Evaluations must have a date and responsible person to allow chronological tracking. | Evaluation |
| RN-22 | Only active plans may give rise to new enrollments. | Plans |
| RN-23 | Sensitive information must not appear unnecessarily in technical logs. | LGPD |
| RN-24 | If the gym blocks delinquent clients, the block must be applied by the access-rules engine, not by facial recognition. | Finance/Access |
| RN-25 | If classes with participant limits are offered, confirmed reservations cannot exceed capacity without an authorized exception. | Schedule |
| RN-26 | Critical changes to permissions, biometrics, and configuration must generate a notice. | Notice |
| RN-27 | A user who performs a problematic action must not be free to erase evidence of their own action. | Audit |
| RN-28 | Exports must respect the same permissions as the screens/APIs. | Security |
| RN-29 | One client's data must never be included in AI context intended for another client. | AI/Privacy |
| RN-30 | AI responses must not be presented as medical diagnoses. | AI |
| RN-31 | The instructor/professional must remain identifiable as responsible for plans they changed/created. | Training |
| RN-32 | Every temporal record must use a consistent date/time format to preserve traceability. | System |
| RN-33 | Deletion/deactivation of an entity must not break historical relationships needed for audit. | Integrity |
| RN-34 | Biometric data must not be sent to ordinary operational reports. | LGPD |
| RN-35 | If a student does not have a valid enrollment, the system must prevent their access. Missing or expired enrollment is invalid. | Access control |
| RN-36 | The turnstile must be released only after the system validates the student's identity, the existence and validity of the enrollment, the contracted modality, and the permitted number of accesses. | Entry authorization |
| RN-37 | As auxiliary information, the gym occupancy system must show the number of people in certain gym spaces by counting people using a computer-vision model connected to surveillance cameras. | Gym occupancy |

**Classification note:** RN-37 describes a computer-vision occupancy counting and display function. RN-08, RN-09, RN-12, RN-14, RN-19, RN-21, and RN-26 also imply flows requiring detail. Their original numbering is preserved; see DEC-10, DEC-11, and DEC-15.

## 6 Technologies and technical constraints

### 6.1 Historical technology entries

The following TEC entries are preserved for traceability only. Where they list
alternatives, DEC-03's approved baseline below—not the historical alternative—is
the active implementation architecture.

| ID | Layer | Indicated technology | Recorded rationale |
| --- | --- | --- | --- |
| TEC-01 | Frontend | React + TypeScript | Componentization, strong ecosystem, and good suitability for a responsive SPA interface |
| TEC-02 | Frontend build | Vite | Simple setup for a React/TypeScript project and production build |
| TEC-03 | Backend | NestJS + Python | Modular architecture, controllers/services/guards, and good REST/OpenAPI support; add firewall; add Docker |
| TEC-04 | Database | PostgreSQL | Domain data is strongly relational and requires constraints/transactions |
| TEC-05 | Auth | Keycloak/OIDC, or secure authentication integrated into the backend for reduced scope | Avoids reinventing multiple identity mechanisms and allows standardized roles |
| TEC-06 | API | REST + JSON + OpenAPI | Suitable for the web interface and external recognition integration |
| TEC-07 | AI | Adapter for an LLM provider | Avoids coupling the domain to a single provider |
| TEC-08 | Infrastructure | Docker Compose | Makes it easier to reproduce frontend/backend/database/identity locally and on any other machine |
| TEC-09 | E-mail | SMTP or e-mail provider API | Needed for invitations and recovery |
| TEC-10 | Tests | Unit + integration + API contract | Particularly important for AI and facial integration |

### 6.1.1 Approved current technology baseline (DEC-03)

| Area | Approved implementation choice |
| --- | --- |
| Architecture/backend | Python 3.13.15 modular monolith; FastAPI 0.141.1. NestJS has no MVP responsibility and requires a future explicit decision. |
| Persistence | PostgreSQL 18.6 with pgvector 0.8.1 for the approved RF-15/RF-18/RF-19 RAG; SQLAlchemy 2.x synchronous access; Alembic migrations; psycopg 3. |
| Frontend | React 19.3.0, TypeScript 5.9.3, Vite 8.3.0, MUI 9.0.0; Node.js 24.21.0 LTS. |
| Authentication | Keycloak 26.6.3 through OIDC; identity model in section 2.2. |
| API | REST + JSON + OpenAPI. |
| E-mail | SMTP adapter; Mailpit 1.30.7 in local Docker development. |
| AI | Provider-independent adapter; Task 11 uses the OpenAI Responses API with configurable `gpt-5.6-luna` behind that boundary. Ollama is an approved local development/test adapter with configurable base URL, model (default `qwen3:8b`), and timeout; it may run through an optional internal Docker Compose profile with persistent model storage, and does not replace OpenAI. Later AI features require their own approved contracts. |
| Runtime/deployment | Docker Compose on a Linux host; host-level UFW; PostgreSQL and other internal services are not directly Internet-exposed. |
| Tests | pytest/FastAPI `TestClient`; Vitest + React Testing Library. No Jest/Supertest for the Python backend. |
| Hosting | Undecided. |

The pinned versions above are canonical; DEC-03 retains their amendment history.
This document does not authorize upgrades.

### 6.2 Technical constraints that must also guide the work

- **Isolated SMTP:** CA-06.4 requires the SMTP server to be isolated in a Docker container. This requirement must be reconciled with the e-mail API alternative in TEC-09.
- **Backend:** TEC-03 mentions NestJS and Python together. Their responsibilities are not defined; the entry must not be interpreted as an automatic choice between the two technologies.
- **Firewall:** the backend entry calls for a firewall but does not specify product, execution location, ports, or rules.
- **Containers and execution:** TEC-03 mentions Docker, and TEC-08 indicates Docker Compose for reproducing frontend, backend, database, and identity on other machines.
- **Authentication:** TEC-05 offers Keycloak/OIDC or secure backend-integrated authentication in a reduced scope. Choose and record an approach before consolidating identity implementation.
- **API contracts:** TEC-06 indicates REST, JSON, and OpenAPI. RF-20 requires a documented JSON contract, integration authentication, validation, and duplicate-event handling.
- **Decoupled AI:** TEC-07 and RNF06 require an integration layer that avoids tying the domain to one LLM provider. The provider and model are not defined.
- **External facial service:** RF-20 assumes an external identification integration. The application need not implement the turnstile's operation algorithm, per CA-20.3; authorization rules remain the system's responsibility.
- **Camera-based counting:** RN-37 mentions a computer-vision model connected to surveillance cameras. It specifies no model, library, camera protocol, or association of that processing with Python.
- **Payments:** RF-31 requires API confirmation but does not select a payment gateway or provider.
- **Tests:** TEC-10 calls for unit, integration, and API-contract tests, with attention to AI and facial-recognition integrations.

Choices still unspecified must be handled under DEC-08–DEC-16 and extension
decision gates. Do not add providers or infrastructure as if they were approved.

## 7 Domain and architecture references

### 7.1 Data model shown in the diagrams

The domain diagrams contain different representations of the data model. They serve as references but do not form one fully reconciled schema.

| Area | Represented entities and concepts |
| --- | --- |
| Identity and administration | User, client, employee, administrator, role, permission, session, recovery, configuration, and audit. |
| Gym and offerings | Gym, plan, subscription or enrollment, charge, payment, gym class, and equipment. |
| Onboarding and health | Onboarding, physical data, complaints, medications, health conditions, and evaluations. |
| Training | Training plan, plan version, plan item, exercise, and completed workout. |
| AI | Interactions, conversation, messages, and training-change proposals. |
| Physical access | Biometrics, facial identification, turnstile, access decision, manual release, entry and exit records, and attendance. |

Recurring conceptual references include the client's link to onboarding and the plan, plan versioning, association of items with exercises, the contracting link to plan and client, and the association of access records with the client.

The diagrams vary in terminology and detail, including subscription versus enrollment and association of AI interactions with items or versions. Before creating migrations, reconcile these points with the task's RFs and RNs; see DEC-17. An entity's presence in a diagram does not by itself define a complete new interface or CRUD flow.

### 7.1.1 Implementation-oriented domain model

This is a domain inventory, not a final SQL schema. Unapproved fields and
cardinalities remain undecided.

| Entity/concept | Purpose, ownership, relationships, privacy/lifecycle |
| --- | --- |
| Account / PersonProfile | Account owns local OIDC linkage, unique normalized e-mail, and no password. One Account-linked personal record owns first name, multiword surname, globally unique validated CPF, phone, and Brazilian address so a client/instructor identity is not duplicated. |
| Client | Client-domain profile with independent UUID and unique Account FK. Owns onboarding, plans, progress, and attendance relationships; role-specific deactivation preserves history and need not deactivate a separately active Employee. |
| Employee/role authorization | Employee has an independent UUID, unique Account FK, role-specific active state, optional validated CNPJ, and currently only the `instructor` specialization. Keycloak and backend policy enforce specialization; one Account may also own a Client when e-mail and CPF match. |
| Onboarding / structured data | Client-owned draft/completed aggregate for approved physical and health fields. Structured values are authoritative; completion/timestamps follow RF-13. Health access is need-to-know. |
| AI onboarding conversation/message | Client-owned resumable EXT-RF-AI-01 interaction that maps into structured onboarding. Raw messages and summary are client-only and retained for five days; structured data remains authoritative. |
| TrainingPlan / TrainingPlanVersion / TrainingPlanItem | Client-owned plan aggregate, immutable/versioned current/history states, responsible professional, structured exercise items. At most one plan may be current and at most one version may be a `proposal` for a client; activating another preserves the prior plan as superseded. |
| Exercise | Referenced prescription content; inactive exercises remain in history under RN-20. Full management flow awaits DEC-15. |
| AI training conversation/message/proposal | Client-scoped RF-18/RF-19 context and proposed changes. A proposal is not a current approved plan; changes use the version lifecycle. |
| EquipmentModel / EquipmentUnit | RF-32 administrative records and RF-33 catalog use UUID-identified logical models and their physical units. Active quantity is derived from inventory-active units for an active model, never stored as an authoritative mutable aggregate. Unit operational/out-of-order state is separate; training usability requires at least one active operational unit. Neither state is live availability. |
| ProgressUpdate | Client-author-owned post with private/shared visibility, moderation, and deletion lifecycle governed by EXT-DEC-SOC-01. Task 26 adds likes/comments for accessible shared, non-hidden posts; Task 27 adds bounded post media, author content/attachment editing, and the shared chronological feed without creating a second post aggregate. No sensitive data is automatically derived into it. |
| SocialProfile / ProfileImage | Client-owned default-on authenticated social projection with optional non-unique nickname, 160-character biography, visibility preference, and a separately stored normalized image. The Client UUID remains canonical; old image bytes are deleted on replacement/removal. |
| ClientFollow | Directed client-to-client relationship with a unique follower/followed pair; no self-follow, request, approval, friendship, or recommendation semantics. |
| PostLike / PostComment | Authenticated interactions attached to a permitted ProgressUpdate. A like is unique per client/post; a comment is author-owned, supports optional text and one normalized image, and is independently moderatable as one aggregate. Both follow post/account deletion. |
| PostImage / CommentImage | Ordered, dedicated normalized media records owned through one ProgressUpdate or PostComment. Posts allow at most four and comments at most one; authorization follows the parent aggregate and replacement/removal/erasure deletes bytes. |
| Plan/Enrollment/Subscription | Client contracting and validity concepts for RF-31/RN-22/RN-35/RN-36. Cardinality, modalities, and validity await DEC-12. |
| Charge/Payment | Client financial records and external confirmation. Provider/model and financial meanings await DEC-12/DEC-13; access is restricted. |
| Biometric data | Separately protected RF-22 data; not ordinary profile data. DEC-09 defines measured quality, calibrated threshold, reference/minimization, replacement, retention, and audit; implementation remains future work. |
| AccessEvent / attendance | Persisted, source-idempotent confirmed client-passage and auditable manual-correction ledger for RF-20/RF-23/Task 22. Passage events resolve an opaque external client reference server-side to their private local Client relationship; DEC-11 separately defines the provider-neutral recognition and idempotent release-request boundary. Occupancy stays governed by DEC-10. |
| Occupancy records | Reconstructable effective client-only count for one logical zone, derived from the confirmed-passage/correction ledger. The authenticated access producer sends a checkpoint heartbeat every 60 seconds; its aggregate state is current through 120 seconds and stale afterwards, while retaining the last count. Future camera observations are auxiliary, zone-declared, 60-second-freshness evidence only; they never overwrite the authoritative count. |
| Presence preference/view | EXT-RF-PRES-01 opt-in state and derived named presence. Persistence and consent lifecycle await EXT-DEC-PRES-01. |
| Class/schedule | RF-30 class occurrences; recurrence, capacity, visibility, and reservations await DEC-14. |

Ownership rules apply at the backend: authenticated clients receive only their
own protected aggregates unless an explicit shared-visibility requirement says
otherwise.

### 7.2 Architecture boundaries

Historical diagrams mention ER modeling and microservices and indicate a modular backend architecture. The embedded images focus on entities and relationships; they do not establish an unambiguous division of services, their contracts, or their deployment.

Therefore, the boundary between modules and processes, allocation of responsibilities between NestJS and Python, selected authentication, and deployment design need to be recorded under DEC-03. The requirement for decoupled integrations remains valid under any chosen solution.

DEC-03 has since selected the current boundary in section 6.1.1; the paragraph
above remains historical modeling context, not an active alternative.

### 7.3 Cross-cutting authenticated API rules

- For a client-owned protected resource, the backend derives the account and
  client from the verified Keycloak subject whenever possible.
- A `client_id` in a path, query, body, local storage, or frontend state is never
  proof that the caller owns that client.
- A client accesses only their protected data unless an explicit requirement
  defines shared visibility, such as EXT-RF-SOC-01, EXT-RF-SOC-02,
  EXT-RF-SOC-03, or EXT-RF-PRES-01.
- Administrative and professional APIs enforce role and functional-need policy
  independently of frontend routes, menus, or hidden controls.
- Direct API calls receive the same denial as the UI; obscuring controls is not
  authorization.
- External adapters receive only the minimum permitted client context and map
  provider failures to controlled application errors.

## 8 MVP and implementation sequence

### 8.1 Explicitly stated MVP

The stated MVP includes the following 15 requirements:

`RF-01`, `RF-02`, `RF-03`, `RF-04`, `RF-05`, `RF-09`, `RF-10`, `RF-11`, `RF-12`, `RF-13`, `RF-15`, `RF-16`, `RF-17`, `RF-18`, and `RF-19`.

The stated critical path is:

Registration → Access → E-mail → Onboarding → AI generation → Training plan → Chat → Dynamic adaptation.

This list does not waive the RNFs and RNs associated with the selected requirements.

DEC-19 adds `EXT-RF-AI-01` to the planned MVP onboarding experience without
claiming that it existed in the original MVP list. `EXT-RF-SOC-01`,
`EXT-RF-EQP-01`, and `EXT-RF-PRES-01` are approved post-MVP extensions.

### 8.2 Dependencies requiring reconciliation

| Dependency | Implication for the MVP |
| --- | --- |
| RF-03 requires a valid photo for enabled clients, while RF-22 is not in the MVP. | Define how initial enablement occurs and when biometrics becomes necessary; DEC-05. |
| RF-09 requires e-mail infrastructure. | Define sending and failure handling before validating invitations, even if RF-06 access recovery is delivered later. |
| RF-15 and RF-19 depend on health context and change approval. | Define blocks, review, and versioning alongside RN-12 through RN-19; DEC-07. |
| RN-14 and RN-19 require full instructor editing and manual training-plan creation. | Detail how those flows fit into the AI delivery; do not consider them implemented merely because RF-15 is ready. |
| RF-04 and RF-05 presume available users and permissions. | Define initial provisioning and the permission matrix; DEC-04. |

The reproducible dependency path now is:

`client provisioning/login → secure and conversational structured onboarding →
validated completion → version lifecycle → AI generation → own current-plan
view → own-context AI chat → approved adaptation → later client modules`.

The original secure-link/form flow remains alongside conversational onboarding
until a later approved decision replaces it.

### 8.3 Suggested sequence for Codex

This order is implementation guidance added in this consolidation; it does not change MVP membership.

| Step | Work | Main references |
| --- | --- | --- |
| 1 | Reconcile decisions affecting the first delivery and prepare the necessary technical foundation. | DEC-01, DEC-03, DEC-04, DEC-05, TEC-01 through TEC-10, and RNF04/RNF06. |
| 2 | Implement authentication, authorization, client registration, and client search/view. | RF-04, RF-05, RF-01, RF-02, and RF-03. |
| 3 | Implement e-mail invitations and the onboarding form with data isolation. | RF-09, RF-10, RF-11, RF-12, and RF-13. |
| 4 | Implement the first plan, viewing, and versioning, along with necessary professional flows. | RF-15, RF-16, RF-17, and RN-12 through RN-19. |
| 5 | Implement chat and adaptation proposals while preserving approval and history. | RF-18, RF-19, RN-16 through RN-18, and RN-29 through RN-31. |
| 6 | Verify the full MVP journey and applicable non-functional criteria. | Criteria of included RFs, RNF01 through RNF06, and relevant rules. |
| 7 | Implement remaining modules in specific tasks according to project priorities. | Remaining RFs, including RF-24/RF-25 and RN-37. |

### 8.4 Scope classification

| Major feature | Classification | Governing requirements/decisions |
| --- | --- | --- |
| Client/account CRUD, auth, authorization | Original MVP; Tasks 02–06 implemented/integration-verified | RF-01–RF-05; DEC-03–DEC-05, DEC-17 |
| Secure-link structured onboarding | Original MVP; partially implemented | RF-09–RF-13; DEC-06, DEC-18 |
| Conversational onboarding | Approved MVP extension; implemented | EXT-RF-AI-01; DEC-06, DEC-08, DEC-18 |
| Portuguese user-facing UI | Approved cross-cutting extension; applies to existing, MVP, and post-MVP screens | EXT-RF-LANG-01; RNF02/RNF03 |
| Training generation/version/current view/chat/adaptation | Original MVP; partially implemented | RF-15–RF-19; DEC-07, DEC-08, DEC-15, DEC-18 |
| Employee management, recovery, onboarding self-review | RF-06/RF-07/RF-08 implemented; RF-14 not started | RF-06–RF-08, RF-14; EXT-DEC-INST-01 |
| Progress sharing | Approved post-MVP extension; implemented | EXT-RF-SOC-01; EXT-DEC-SOC-01; Task 20 |
| Social client profiles/interactions | Approved post-MVP extension; planned | EXT-RF-SOC-02; EXT-DEC-SOC-02; Task 26 |
| Authenticated chronological social feed | Approved post-MVP extension; planned | EXT-RF-SOC-03; EXT-DEC-SOC-03; Task 27 |
| Equipment management/catalog | Original post-MVP; implemented | RF-32, RF-33 |
| Equipment quantity | Approved post-MVP extension; implemented | EXT-RF-EQP-01; EXT-DEC-EQP-01 |
| Instructor professional area | Implemented; Task 37 closed by user direction with formal evidence follow-up | RF-07/RF-08; EXT-RF-INST-01–EXT-RF-INST-05; EXT-DEC-INST-01 |
| Access/attendance/anonymous occupancy | Original post-MVP; Task 22 implemented | RF-23–RF-25; confirmed-passage/correction ledger and aggregate-only client view. RF-20–RF-22 biometric/access work remains separate |
| Named visible presence | Approved post-MVP extension; implemented | EXT-RF-PRES-01; Task 23, EXT-DEC-PRES-01 |
| Billing/plans/dashboard/classes | Original post-MVP; not started | RF-26–RF-31; DEC-12–DEC-14 |
| CA-03.4 biometric readiness | Deferred, not satisfied | RF-03/CA-03.4, RF-22, DEC-05 |

## 9 Approved and unresolved decisions

This section gives the canonical status of each decision. `docs/decisions.md`
retains the chronological decision history.

| ID | Status | Canonical result or remaining question | Affected work |
| --- | --- | --- | --- |
| DEC-01 | Unresolved; non-blocking while original scope is used | Professor validation may later change scope. Preserve all original requirements and the explicit original MVP meanwhile. | Overall scope; no independent task is blocked. |
| DEC-02 | **Resolved** | The historical `X` suffix has no separate meaning; canonical occupancy requirements are RF-24 and RF-25. | Occupancy tasks. |
| DEC-03 | **Resolved** | Python/FastAPI modular monolith, PostgreSQL/SQLAlchemy/Alembic, React/TS/Vite/MUI, Keycloak/OIDC, SMTP/Mailpit, Docker Compose/Linux/UFW, provider-independent AI adapters, and approved pinned baseline. NestJS has no MVP role. | All architecture and external adapters. |
| DEC-04 | **Resolved for current roles/provisioning** | Roles are client, employee, attendant, instructor, admin. Initial admin is environment-bootstrapped; clients and instructors use authorized administrative provisioning with durable reconciliation and secure first access. One matching Account may hold both client and instructor roles with independent role-active state. Health/biometric access follows section 2.1. | Auth, clients, employees, health, training. |
| DEC-05 | **Resolved** | `account_active` controls application login only; `gym_access_enabled`/physical eligibility is separate. CA-03.4 remains explicitly deferred to RF-22 and unsatisfied. | RF-03/RF-04 and future physical access. |
| DEC-06 | Resolved for implemented flows | Invitation tokens are 24-hour, client-bound, purpose-bound, hashed, single-use on intentional redemption, and superseded by resends. The onboarding schema, draft behavior, and completion prerequisites are approved. Password recovery uses Keycloak-owned UPDATE_PASSWORD email links with a user-approved 15-minute lifetime. | Tasks 07, 09, 10, 11, 12 and RF-06 recovery. |
| DEC-07 | **Resolved for Tasks 13–17** | Plan-version states are proposal/approved/current/superseded; only instructors approve/activate; AI never does. Relevant health onboarding data must influence a proposal but does not automatically block its generation; mandatory instructor review is the safety gate. Task 17 applies this lifecycle to client-confirmed proposals and immutable history. | Tasks 13–17. |
| DEC-08 | **Resolved for Tasks 11, 14, 16, and 17** | OpenAI Responses API, configurable `gpt-5.6-luna`, provider-neutral adapter, constrained output where applicable, minimized bounded context, ten-second timeout, and one retry. Ollama is additionally approved as a configurable local development/test adapter and does not alter OpenAI behavior. Task 17 uses validated structured proposal output only after explicit client confirmation. | Tasks 11, 14, 16, 17, and later AI tasks with their own scope-specific safety contracts. |
| DEC-09 | **Resolved for biometric recognition and enrollment** | Measured configured-system precision is at least 95%; the provider/model uses a calibrated configurable match threshold; below-threshold results are rejected; biometric references, replacement, retention, and non-sensitive auditing are separately protected. CompreFace is a non-binding personal-use self-hosted pilot recommendation, not a selected provider. | RF-21/RF-22. |
| DEC-10 | **Resolved for Task 22 occupancy** | Confirmed client-passage ledger is authoritative for one logical zone; cameras are deferred auxiliary observations with declared coverage, 60-second freshness, and no overwrite/blending behavior. | RF-24/RF-25, RN-37, Task 22. |
| DEC-11 | **Resolved for approved integration boundaries** | Confirmed-passage occupancy ingestion uses source-idempotent events with opaque client references resolved privately to local Clients; its public view is aggregate-only. Provider-neutral facial recognition uses server-side credentials, correlated recognition IDs, and idempotent release requests to an external turnstile. It neither controls physical passage nor changes DEC-10 occupancy semantics. | Task 22; later RF-20–RF-23 biometric/access implementation. |
| DEC-12 | Unresolved | Plan/enrollment/payment model, validity/modalities/access allowance, confirmation, renewal, delinquency and purchasable plans. | RF-31, RN-22/RN-24/RN-35/RN-36. |
| DEC-13 | Unresolved | Financial meanings and calculations, periods and filters; profit is not automatically revenue. | RF-26–RF-29. |
| DEC-14 | Unresolved | Class recurrence, visibility, reservation/capacity and authorized exceptions. | RF-30/RN-25. |
| DEC-15 | **Resolved for Tasks 13, 15, and 17** | Instructors may manually create and edit proposals; the minimum version/item model, responsibility metadata, one current plan per client, and Task 17 review of recognized exercise candidates are approved. Exercise catalog, evaluations, completed workouts, notices, and export remain future work. | Tasks 13, 15, and 17 may proceed; later affected tasks need their remaining gates. |
| DEC-16 | **Resolved for personal-use MVP verification** | One normal active user, a three-request burst, approximately 50 synthetic clients, ten-run performance samples, approved adapter timeouts, three representative viewports, checklist-based intended-user testing, accessibility checks, an eight-hour local availability soak, five-minute restart recovery, failure isolation, and maintainability/integration evidence. No commercial-scale load, high availability, redundancy, or production uptime SLA is required. | Task 19 formal end-to-end RNF verification may proceed. |
| DEC-17 | **Resolved for identity/client/employee model** | Independent Account, Client, and Employee UUIDs; unique normalized Account e-mail and nullable Keycloak subject; unique Account↔Client and Account↔Employee links; one Account-linked personal record with unique CPF; no local credentials. | Client/employee identity and later linked domain schemas. |
| DEC-18 | Partially resolved | Health/onboarding policy plus Task 11's client-only raw conversation, five-day retention, minimized AI context, logging, failure safety, and idempotency policy are approved. Biometric storage/replacement/retention is governed by DEC-09. | Tasks 10 and 11 may proceed. |

DEC-19 is a later approved decision, not an original question: it records the
client-facing direction and four of the extension requirements in section 3.1.
EXT-RF-LANG-01 was approved separately as a cross-cutting language rule.

### 9.1 Extension decision gates

| ID | Status | Required decision | Expected task |
| --- | --- | --- | --- |
| EXT-DEC-SOC-01 | **Resolved for Task 20** | Private by default; shared updates are visible to active authenticated clients; shared-only administrator hide/restore moderation with a reason; author-only edit/delete; contentless deletion tombstone and stated lifecycle. | Controlled progress sharing may proceed. |
| EXT-DEC-SOC-02 | **Resolved for Task 26** | Default-on authenticated social profiles; optional nickname/bio and client-owned image lifecycle; unilateral following; bounded likes/comments; moderation, erasure, presence separation, and future-feed boundary. | Social profile redesign may proceed. |
| EXT-DEC-SOC-03 | **Resolved for Task 27** | Authenticated newest-first shared-post feed; private-by-default publishing; bounded post/comment media; author edits; private-profile shell; cursor pagination; aggregate moderation/erasure; no ranking or replies. | Task 27 feed redesign may proceed. |
| EXT-DEC-EQP-01 | **Resolved for Task 21** | UUID-identified `EquipmentModel` canonical grouping; each physical `EquipmentUnit` belongs to one model; active quantity is derived from active units, not a mutable aggregate; no live availability semantics. | Equipment catalog and quantities may proceed. |
| EXT-DEC-PRES-01 | **Resolved for Task 23** | Default-off client-owned profile tag only; derived from fresh confirmed passages with a 12-hour limit; immediate opt-out; no directory, staff override, or occupancy impact. | Opt-in profile presence may proceed. |
| EXT-DEC-INST-01 | **Resolved for Tasks 28–37** | Shared person identity and RF-07/RF-08 instructor provisioning; dedicated instructor area; public-profile-only read-only feed; one cross-source plan draft; plan responsibility/history/search/onboarding workflows; separate equipment operational state; ViaCEP-assisted but always editable Brazilian addresses. | Instructor professional-area tasks may proceed in dependency order. |

### 9.2 Privacy and sensitive-data rules

| Data category | Access and handling boundary |
| --- | --- |
| Account/profile | Owner and explicitly authorized administrative operations; normalized e-mail and Account-linked personal data are authoritative. CPF/CNPJ, phone, and address are restricted personal data and never enter instructor search/social projections, ordinary logs, URLs, or external AI context. Client/employee administrative detail remains authorized-only. EXT-RF-SOC-02 exposes only its minimized authenticated social projection when enabled. |
| Health/onboarding | Client and only staff with functional need; attendants and admin status alone do not grant medical access. Apply RN-11/RN-23 and DEC-18. |
| Biometrics | Separate from ordinary profile data; authorized biometric staff only; never common reports or social/presence views. Apply RN-10/RN-34. |
| Authentication | Keycloak owns credentials. Tokens/secrets are not stored as domain data or logged. Subject is an external reference only. |
| Financial | Client's own allowed view and explicitly authorized operations only; never social or presence content. |
| Progress/social | Author-owned; visibility is explicit. No sensitive category is automatically copied into a post. |
| Attendance/presence | Anonymous occupancy is distinct from named opt-in presence. Identifiable events require approved operational access and privacy rules. |
| AI context | Minimum permitted context for the resolved authenticated client only. Never cross-client; no diagnosis; sensitive prompts/responses are not unnecessarily logged. |

No retention duration is invented. RN-18/RN-27/RN-33 historical and audit
preservation applies where relevant, subject to an approved sensitive-data
retention decision.

### 9.3 Current implementation status

Status is evidence-based from completed tasks and their tests, not inferred from
unchecked boxes or planned files.

| Requirement | Scope | Status | Dependency/decision | Notes |
| --- | --- | --- | --- | --- |
| Foundation | Enabler | Implemented | DEC-03 | Task 01 verified baseline. |
| RF-04 | Original MVP | Implemented | DEC-03–DEC-05 | Task 02; Task 06 integration verifies real provisioned clients. |
| RF-05 | Original MVP | Implemented | DEC-04 | Task 03; client-role denial reverified in Task 06. |
| RF-01/RF-02 | Original MVP | Implemented | DEC-04/DEC-17; EXT-DEC-INST-01 | Task 28 structured person/contact/address data, shared identity, and CEP assistance; Task 37 automated and scoped browser checks passed. |
| RF-03 | Original MVP | **Partially implemented** | DEC-05; EXT-DEC-INST-01 | CA-03.1–CA-03.3 and CA-03.5–CA-03.6 implemented and integration-tested, including all-field editing, independent role activity, and durable Keycloak reconciliation. CA-03.4 remains deferred and unsatisfied. |
| RF-07/RF-08 | Original post-MVP | Implemented | DEC-04/DEC-17; EXT-DEC-INST-01 | Task 29: instructor employee registration, management, provisioning, dual-role linkage, and independent activation; employee API validation/error regressions verified. Task 37 technical checks passed at all three required viewports; intended-user and soak evidence remain pending. |
| Client identity provisioning | Approved DEC integration | Implemented | DEC-03/04/05/17 | Task 06: client-only Keycloak identity, subject linkage, required action, and independent durable reconciliation. |
| RF-09 | Original MVP | Implemented | DEC-03/DEC-04/DEC-06/DEC-17 | Task 07: provisioned active client, hashed 24-hour invitation, SMTP outcome persistence, resend invalidation. |
| Frontend design system and existing UI restyle | Visual implementation enabler | Implemented | `docs/frontend-design.md` | Task 08: shared MUI theme, shells, and restyle; preserves Tasks 01–07 behavior. |
| Keycloak authentication theme | Cross-cutting UI integration | Implemented | DEC-03; `docs/frontend-design.md` | Repository-managed `academia` theme is selected by the managed realm and supplied through Docker Compose; Keycloak continues to own credentials and OIDC flows. |
| RF-10 | Original MVP | Implemented | DEC-06 | Task 09: secure client-scoped invitation validation and intentional redemption. |
| RF-11/RF-12 | Original MVP | Implemented | DEC-06/DEC-18 | Task 10: client-scoped structured draft, physical/health validation, separate persistence, and non-sensitive audit evidence. |
| RF-13 | Original MVP | Implemented | DEC-06 | Task 12: shared authoritative validation, intentional atomic completion timestamp, and a downstream completed-onboarding contract. |
| EXT-RF-AI-01 | Approved MVP extension | Implemented | DEC-06/08/18 | Task 11: client-scoped resumable interview, final validated structured extraction, bounded context, idempotency, and five-day raw-message retention. |
| EXT-RF-LANG-01 | Approved cross-cutting extension | Scoped verification performed | RNF02/RNF03 | Task 37 audited affected administrative/instructor journeys in pt-BR at three sizes. Hosted Keycloak screens were not newly browser-audited; no blanket verification claim. |
| RF-17 | Original MVP | Implemented | DEC-07/DEC-15 | Task 13 plus follow-up: immutable version lifecycle, current selection, responsibility metadata, manual proposal path, and the client-wide single-draft rule. |
| RF-15 | Original MVP | Implemented | DEC-07/08/15/18 | Task 14 plus follow-up: completed-onboarding-scoped AI generation and reuse of the sole client draft; instructor review remains mandatory. |
| RF-16 | Original MVP | Implemented | DEC-07/15/16 | Task 15: authenticated client-only current-sheet API and responsive exercise view, including empty/loading/error states. |
| RF-18 | Original MVP | Implemented | DEC-08/DEC-18 | Task 16 plus follow-up: client-only persisted training chat, bounded own-context, idempotency, controlled failures, and validated editing of the sole client draft regardless of creator. |
| RF-19 | Original MVP | Implemented | DEC-07/08/15; EXT-DEC-EQP-01 | Tasks 17, 25, and 36: client-confirmed adaptation, instructor review, immutable history, and server-validated EquipmentModel references. New/changed machine items require an active operational unit; exactly unchanged approved items retain their history. Inventory and operational state never imply live availability. |
| MVP frontend polish | Visual implementation enabler | Implemented | `docs/frontend-design.md` | Task 18: shared visual, responsive, loading/empty/error, pt-BR copy, and accessibility consistency pass; Task 19 retains end-to-end verification. |
| MVP integrated verification | Original MVP verification | Planned | DEC-16 | Task 19. |
| EXT-RF-SOC-01 | Approved post-MVP extension | Implemented | EXT-DEC-SOC-01 | Task 20. |
| EXT-RF-SOC-02 | Approved post-MVP extension | Planned | EXT-DEC-SOC-02 | Task 26. |
| EXT-RF-SOC-03 | Approved post-MVP extension | Planned | EXT-DEC-SOC-03 | Task 27. |
| RF-32/RF-33 + EXT-RF-EQP-01 | Original post-MVP + extension | Implemented | Resolved EXT-DEC-EQP-01 | Task 21: authorized two-level model/unit management and public active catalog with derived total. |
| RF-23–RF-25 | Original post-MVP | Implemented | Resolved Task 22 DEC-10/DEC-11 boundary | Task 22: confirmed-passage/correction ledger, derived non-negative count, authenticated source heartbeats, and aggregate-only client view. |
| EXT-RF-PRES-01 | Approved post-MVP extension | Implemented | Task 22/EXT-DEC-PRES-01 | Task 23. |
| EXT-RF-INST-01–EXT-RF-INST-05 | Approved post-MVP extension | Implemented; Task 37 done by user direction | RF-07/RF-08; EXT-DEC-INST-01 | Tasks 28–36 implemented. Task 37 technical checks passed: 248 backend tests including PostgreSQL, 115 frontend tests, scoped browser/performance/restart checks. User requested Task 37 closure and will perform the checklist; checklist results and eight-hour soak remain unverified follow-up evidence, not passing criteria. See [Task 37 report](tasks/37-instructor-role-integrated-verification-report.md). |
| RF-06 | Approved post-MVP | Implemented | DEC-06 | Admin client-details and own-profile recovery actions; Keycloak password setup email, 15-minute expiry, authenticated ownership checks and shared resend cooldown. |
| Remaining RF-14, RF-20–RF-22, RF-26–RF-31 | Original post-MVP | Not started | Applicable DEC items | Preserved; no implementation claim. |

## 10 Codex workflow

### 10.1 Historical task-model constraints

- Define the functionality, module, and files or folders that may be changed.
- Do not change layers, Docker, authentication, database, or frontend when outside the task's scope.
- Do not add dependencies without justification and approval.
- Create or adjust only tests related to the functionality.
- Run only tests related to the task.
- Earlier task guidance requested a completion response of at most 10 lines. Current
  `AGENTS.md` and task-file completion requirements govern the actual report
  format while preserving the same required content.

### 10.2 Traceable task template

The template below uses identifiers in this file. Replace bracketed fields for each task.

```text
Task: implement [specific functionality].

Context:
- Read AGENTS.md and docs/requirements.md.
- Use docs/requirements.md as the canonical specification; consult
  docs/decisions.md and docs/product-extensions.md only for supporting history.
- The system has [relevant modules].
- The functionality belongs to module [name].
- Functional requirements: [RF-XX].
- Non-functional requirements: [RNFXX].
- Business rules: [RN-XX].
- Recorded decisions: [DEC-XX and the corresponding decision].

Permitted scope:
- Change only [files/folders].
- Do not change [layers or modules outside the task].
- Do not add dependencies without justification and approval.

Expected behavior:
1. [Behavior tied to the requirement].
2. [Behavior tied to the requirement].

Acceptance criteria:
- [CA-XX.Y and verifiable condition].
- [CA-XX.Z and verifiable condition].

Tests:
- Create or adjust only tests related to the functionality.
- Run only the related tests.
- Record results and report what could not be verified.

Final response:
- At most 10 lines.
- Report changed files, tests run, and pending issues.
```

### 10.3 Task completion

Consider a task complete when its acceptance criteria have been verified, the relevant business rules have been followed, related test results have been recorded, and remaining limitations are explicit. Mark only criteria actually met; leave the others pending.

## 11 Terminal unresolved-decision index

Only genuinely unresolved items appear here. Their full questions, impact, and
expected tasks are in section 9 and the implementation plan. Do not resolve them
by inference.

- **DEC-01:** professor-validated final scope; non-blocking while preserving the
  original catalog/MVP.
- **DEC-02:** resolved; historical RF-24X/RF-25X identifiers are normalized to
  RF-24/RF-25 without changing behavior.
- **DEC-06:** resolved for implemented invitation, onboarding and recovery flows.
  Recovery uses Keycloak password-setup emails with a 15-minute link lifetime,
  approved by the user on 2026-09-27.
- **DEC-07:** resolved for Tasks 13–17. Later adaptation work must preserve the
  approved proposal/review lifecycle.
- **DEC-08:** resolved for Tasks 11, 14, 16, and 17. Later AI work still
  requires its own applicable contracts and safety decisions.
- **DEC-09:** resolved for biometric quality/handling; it governs future RF-21/RF-22 implementation.
- **DEC-10:** resolved for Task 22: confirmed client-passage ledger is
  authoritative; future camera observations are 60-second-fresh auxiliary
  evidence and cannot overwrite/blend the count.
- **DEC-11:** resolved for the approved confirmed-passage and
  facial-recognition/release integration boundaries. Physical eligibility rules
  remain governed by their applicable requirements and DEC-12.
- **DEC-12:** plans, enrollment, payment, and entry eligibility details; blocks
  RF-31 and related physical-access work.
- **DEC-13:** financial indicator meanings; blocks RF-28/RF-29 financial metrics.
- **DEC-14:** class scheduling/capacity/reservation model; blocks RF-30 details.
- **DEC-15:** resolved for Task 17's exercise-candidate review scope; remaining
  catalog/evaluation flows retain their separate gates.
- **DEC-16:** resolved for personal-use MVP RNF measurement; Task 19 formal
  verification may proceed under the bounded load, viewport, usability,
  accessibility, availability/recovery, failure-isolation, maintainability, and
  integration protocol in section 4.0.1.
- **DEC-18:** health/onboarding and Task 11 AI-conversation storage, access,
  logging, retention, and failure-safety policy are approved. Biometric
  lifecycle is governed separately by DEC-09.
- **EXT-DEC-SOC-01:** resolved sharing audience and lifecycle for Task 20.
- **EXT-DEC-SOC-02:** resolved social-profile, image, follow, like, comment,
  moderation, erasure, and future-feed boundaries for Task 26.
- **EXT-DEC-SOC-03:** resolved the authenticated chronological feed, bounded
  post/comment media, author edits, private-profile shell, cursor pagination,
  moderation/erasure, and no-ranking/no-replies boundaries for Task 27.
- **EXT-DEC-EQP-01:** resolved for Task 21 with UUID-identified
  `EquipmentModel` grouping, physical `EquipmentUnit` inventory, derived
  active quantity, and no live-availability semantics.
- **EXT-DEC-PRES-01:** named-presence consent/data/source/retention model; blocks
  Task 23 together with Task 22.
- **EXT-DEC-INST-01:** resolved RF-07/RF-08 identity/contact/provisioning,
  instructor navigation/feed audience, single-draft training workflows,
  onboarding access, and equipment operational-state boundaries for Tasks
  28–37.

### Production deployment hardening amendment — 2026-09-27

User-approved deployment-only extension to TEC-03/08/09 and RF-04/05:
provide a separate Linux/Docker Compose production configuration with a free
Nginx HTTPS gateway, compiled frontend, non-root application processes, private
internal services, bounded requests, mounted secrets, brute-force protection,
and documented firewall, monitoring and backup/recovery operations. Existing
local development commands and application business workflows remain available.
Nginx is approved as a gateway dependency; use the verified stable 1.30.5 image.
Keycloak remains pinned to 26.6.3 at the user's explicit request. Administrator
MFA preparation is approved, but enforcement is deferred and must not change
the current login steps. The facial pilot remains unchanged and retains its
existing limitations. Hosting/domain selection and actual host firewall/public
rollout remain deployment prerequisites, not implied completed actions.

Acceptance: production configuration publishes only its intended HTTPS/redirect
gateway; internal databases, identity management and metrics are restricted;
existing login/logout, provisioning, invitations, API contracts, media and
frontend routes remain usable; controlled limits return understandable failure
responses; configuration contains no committed secrets; backup/restore and
monitoring procedures identify external prerequisites and are exercised with
synthetic data; development regression tests remain passing. This amendment
does not approve changing gym business rules or upgrading Keycloak.

### Fluid assistant amendment — 2026-09-27

The owner approved improving onboarding and post-onboarding conversations to
accept multiple facts per message, retain verified interview answers, correct
only affected information and ask targeted clarifications without restarting.
This refines EXT-RF-AI-01 and RF-11–13/18–19 within their existing privacy and
training-approval boundaries. Each onboarding message may now trigger a
schema-constrained extraction into client-owned, five-day interview working
state. This supersedes DEC-08's extraction-only-at-the-end restriction; the
structured onboarding draft is still updated only after complete verified
answers pass final validation, and completion still requires the client's
explicit review/action. Form edits override stale working state. Corrections
remain possible in chat until onboarding is completed; completed medical data
and approved/current training plans cannot be silently changed.

Acceptance: multiple supported facts are collected together; unmentioned facts
survive corrections and context-window truncation; ambiguous corrections request
clarification and block readiness; progress survives reload; clients can review
collected answers and correct them before completion; provider failures preserve
prior verified state; retries/concurrent submissions cannot apply duplicate or
stale corrections. Training chat distinguishes attributed client reports from
assistant suggestions, honors explicit corrections in bounded retained context,
and accurately communicates whether a draft change was actually persisted.
Client isolation, existing five-/30-day conversation retention, backend validation,
manual fallback, single-draft revision protection and instructor approval remain
mandatory. No model replacement, new dependency or new health schema is approved
by this amendment.

### Conversational answer recovery amendment — 2026-09-27

The owner approved natural numeric answers, explicit rejection feedback,
repeated-question recovery, deterministic shortcuts and privacy-safe AI diagnostics
for EXT-RF-AI-01/RF-11–13 and the existing RF-18 integration. A preceding physical
question may provide the unit for an otherwise unambiguous personal answer such
as “estou com 82”. Explicit units, targets, negation, uncertainty and third-party
references must not be discarded to manufacture an answer. Clear measurements,
short categorical answers and supported explicit corrections may bypass the
provider only when the entire message is understood; additional free text keeps
the provider path. Existing schema validation and explicit completion remain.

Acceptance: uncertain/conflicting measurements can be proposed but require an
explicit confirmation before persistence; rejections explain what needs
clarification; two failed answers to the same field offer direct measurement
entry or the existing form without discarding other answers. Retry replay cannot
increase this counter or reapply a suggestion. Suggestions/counters expire with
interview state and are superseded by manual edits. Diagnostics report operation,
path, elapsed time and controlled outcome/rejection categories, without message
text, answer values, identities, tokens or raw provider errors. No model,
retention policy, dependency, schema migration or plan-approval change is approved.
