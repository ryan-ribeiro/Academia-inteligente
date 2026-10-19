# Academia Inteligente — Frontend Design Direction

**Status:** approved visual direction (2026-09-21). This document governs the
application's visual/UI language. Product behavior and authorization remain
governed by `docs/requirements.md` and `docs/decisions.md`.

**Reference:** [Strive Gym Club](https://www.strivegymclub.com/) is inspiration
for confident type, strong contrast, broad visual sections, restrained accents,
and fitness imagery. This project uses its own brand, layout decisions, copy,
code, and assets. Do not copy the reference's source, logo, text, images, exact
palette, or page composition.

## Principles

- Athletic, modern, premium, direct, and energetic without decoration for its
  own sake. Preserve information clarity in operational and sensitive screens.
- Use one React/MUI design system for public, client, and admin experiences.
  Client pages may have more visual space and imagery; admin pages use the same
  tokens with denser tables, lists, and forms.
- Establish shared foundations in Task 08 before building more client screens.
  Task 18 checks consistency after major MVP screens exist.

## Language and copy

- Follow EXT-RF-LANG-01 in `docs/requirements.md`: application-controlled UI
  copy is Brazilian Portuguese (`pt-BR`) across public, client, and admin areas.
  Keep this design document, task prompts, source identifiers, and API contracts
  in English. Do not translate user-authored text or proper names.
- Cover headings, navigation, buttons, form labels/help, validation, loading,
  empty, success, error and authorization states, dialogs, toasts, document
  titles, accessible names, and in-app AI onboarding/training responses. Do not
  surface raw English provider errors to users.
- Use appropriate `pt-BR` presentation of dates, times, numbers, and currency
  where displayed. Keep established English gym or technical terms such as
  “bulking” when they are clearer than an artificial translation.
- Reuse shared wording and formatting helpers where available. Check real
  phone, tablet, and desktop flows for unintended English copy; language
  changes must not weaken validation, privacy, or accessibility.

## Tokens and foundations

- **Typography:** Use a freely available or system-compatible sans-serif
  strategy; do not add paid/proprietary fonts. Define display, page title,
  section title, body, label, caption, and compact admin-data roles in the MUI
  theme. Large/display headings may use uppercase selectively. Forms, health
  text, training instructions, chat, and tables use readable mixed case.
- **Semantic color:** Start from an original ink/chalk/coral direction, not
  Strive's exact values. Suggested dark tokens: background `#10181B`, surface
  `#1B272B`, elevated surface `#26363B`, primary text `#F5F7F4`,
  secondary text `#B7C5C6`, accent `#FF8564`, accent contrast
  `#172024`, border `#405157`, success `#85D8AD`, warning
  `#F5C968`, error `#FF9A91`, info `#90CBE9`. A light admin content
  surface may use background `#F2F4F1`, surface `#FFFFFF`, primary text
  `#172024`, secondary text `#4D5E62`, and a deeper accent for text/icons.
  Verify actual combinations against contrast requirements before shipping.
  Status and validation always include words/icons, never color alone.
- **Spacing and shape:** Use the MUI 8 px rhythm with smaller 4 px increments
  only when needed. Establish container widths, section spacing, card padding,
  border radii, borders, and restrained elevation as reusable tokens. Prefer
  coherent grouped sections over many unrelated cards or one-off values.
- **Component hierarchy:** Define consistent primary/secondary/quiet and
  destructive button styles; text fields, selects, checkboxes, radios,
  switches, chips/badges, cards, dialogs, alerts, snackbars/toasts,
  skeletons/progress indicators, empty/error states, page/section headers,
  responsive containers, and navigation. Reuse MUI theme overrides and shared
  components before adding local style rules. Do not add another UI framework.

## Layout and interaction

- **Public/entry:** An unauthenticated route redirects directly to the Keycloak
  sign-in flow; it does not render a separate welcome/entry screen. Auth
  callback, redirecting, expired-session, unauthorized-route, loading, and
  error states belong to the same system. A controlled error may offer retry.
  React only starts the OIDC redirect; it never renders or receives credentials.
  Keycloak-hosted credential, first-access, password-reset, informational, and
  logout pages are part of the application experience and use the
  repository-managed `academia` login theme at
  `keycloak/themes/academia/login`. The theme extends `keycloak.v2` and favors
  CSS/resources over template overrides, preserving Keycloak form semantics,
  required actions, and accessible error associations. It uses the same
  ink/chalk/coral tokens, system-compatible typography, 8 px-derived spacing,
  surfaces, input/button hierarchy, visible focus treatment, and pt-BR
  localization as the React application. Its branding is Academia Inteligente,
  never Keycloak implementation terminology. The theme is mounted by Docker
  Compose and selected by the managed realm configuration, so it must work on a
  clean deployment without an admin-console change. Verify it on phone,
  tablet, and desktop; decorative backgrounds may not obscure forms or cause
  horizontal scrolling.
- **Login recovery:** expose Keycloak's native "Esqueceu sua senha?" link as an
  outlined secondary action using the existing theme. Its email-entry page
  explains the 15-minute lifetime and uses generic confirmation for all account
  lookups. Password entry stays on Keycloak-hosted forms.
- **ClientShell:** Reusable authenticated navigation, page header, main action,
  content width, responsive sections, and feedback. On medium and larger
  screens, client navigation is a persistent left sidebar so the active page
  has a stable reading area; the brand sits above the destinations and sign-out
  sits at the sidebar's lower edge, immediately below the compact own-profile
  picture and username link. The obsolete client home destination is omitted:
  an incomplete onboarding opens at onboarding and a completed one at Feed. On phone, use the compact top header and a
  keyboard-accessible collapsible side panel for touch navigation instead of
  shrinking the sidebar into the content. The
  `Assistente` destination is the single client-facing AI entry:
  it presents guided onboarding while onboarding is incomplete and training
  assistance afterward, without a second chat destination. Planned destinations include onboarding, training, AI,
  progress, equipment, and profile when implemented. Show the anonymous occupancy count as a compact person-and-number
  indicator in the client navigation, never as a named presence directory or a separate client destination.
- **AdminShell:** Same type family, accent, controls, and feedback, with denser
  client search/list/detail/edit and status views. Make account state and
  provisioning/invitation outcomes legible; retain clear action hierarchy.
  Confirmation UI is used for genuinely consequential actions as approved by
  the owning workflow, not added as a new business rule by styling alone.
- **InstructorShell:** Reuse the ClientShell responsive navigation mechanics and
  the denser operational clarity of AdminShell without combining their
  permissions. Its ordered destinations are Feed, Planos pendentes, Meus
  planos, Todos os planos, Clientes, Equipamentos, and Perfil; Feed is the
  default and there is no home/dashboard item. On larger screens use the shared
  persistent sidebar pattern; on phone use the same keyboard-accessible compact
  header/panel behavior. Plan review, client workspace, sensitive onboarding,
  and equipment state use clear operational hierarchy rather than decorative
  imagery. The read-only feed reuses social cards but omits every interaction
  composer/control. Perfil is a deliberate pt-BR future-feature state until an
  instructor social profile is separately specified.
- **Dual-role area switch:** when the backend-verified session has both active
  client and instructor roles, both sidebars show a compact current-area panel
  above the account/sign-out controls, separate from the ordered menu. Reuse
  theme surfaces, a subtle coral border/tint, and an outlined target-area link
  with a decorative exchange icon. Keep the same control in the mobile drawer,
  close the drawer on navigation, and retain keyboard focus styles and a
  minimum 44 px target. Single-role sessions do not show it. Switching uses the
  same session and does not combine menus or modify authorization.
- **Administrative person forms:** Client and employee create/edit screens
  group identity, contact, and address fields. Keep first name and surname
  separate, allow a multiword surname, format CPF/CNPJ/phone/CEP for reading,
  and expose validation without relying on masks alone. CEP assistance may
  prefill street, neighborhood, city, and UF, but all address fields stay
  editable and provider failure leaves an obvious manual-entry path. Never
  clear valid manual values merely because lookup fails.
- **Facial enrollment:** Reuse `FacialEnrollment` in both administrative person
  forms. Keep it as one bordered section with status, explicit verification,
  capture/replacement/revocation actions, and local feedback. New registration
  stays unavailable until a capture is ready or shared-person reuse is verified.
  `WebcamCapture` provides the accessible MUI dialog and live preview; capture is
  button-triggered, has no upload input, and stops camera tracks on close/unmount.
  Keep transient images out of component state and persistent browser storage.
  Failed/uncertain requests preserve ordinary form fields and expose result
  recovery; changing identity invalidates the prior readiness proof.
- **Facial access:** `/admin/acesso-facial` uses the AdminShell with the simulated
  passage panel and reasoned presence correction alongside each other on desktop,
  stacked on phone/tablet, followed by filtered recent events. Keep recognition
  and passage confirmation separate, show identified client names and expiration,
  offer safe result recovery, and explain deferred liveness. Reuse WebcamCapture;
  no upload field or automatic scanning. History is a responsive semantic list
  with bounded cursor loading and localized result/time labels. Provider failure
  must preserve the last occupancy count and show an explicit service retry.
- **Onboarding:** Invitation entry leads into a deliberate client journey.
  Group physical and health fields into understandable sections/steps; show
  required/optional status and validation plainly. Conversation and structured
  progress coexist without visualizing health information sensationally.
  Completion has a concise review and clear action.
- **Training:** Current plan is optimized for use during a workout on a phone:
  session → exercise → sets/repetitions/time/load/rest → instructions. Group
  related values rather than giving every value a separate card. Review,
  proposal, approved, and history states remain distinct where approved.
  Client AI proposals show a division title, the client's goal in plain language,
  the pending instructor-review status, and a semantic exercise table with order,
  exercise, sets, repetitions or duration, individual load guidance, and rest.
  A multi-day proposal shows separate `Treino A`, `Treino B`, `Treino C` sections,
  each with its own complete ordered table. Keep day labels visible in section
  titles and restart row numbering within each table; reuse the existing shared
  table renderer and preserve all exercises and source information.
  Keep wide tables inside a keyboard-accessible horizontal scroll region on
  small screens. Retain knowledge sources and limitations next to the proposal.
  The client explicitly sends a satisfactory draft for instructor review from
  the chat or current-training page; show unsent, sending, sent, and error states.
  Sending never presents the proposal as approved or active.
  Exercise requests can target one or several muscles. Keep the sheet focused
  on those requested groups. **Enviar rascunho para minha revisão** sends the
  displayed sheet directly to the instructor, with explicit destination and
  sent/error feedback. Instructor review can show the current plan alongside
  the submitted sheet and select individual suggested exercises to append into
  the next draft version; require at least one explicit selection and preserve
  unselected suggestions outside that combined draft. Existing exercises remain;
  the combined sheet remains subject to explicit approval.
- **Instructor plan browsing:** Pending, own, and all-plan collections use a
  compact selectable list beside a focused reading pane on larger desktops,
  within the shared shell's wider content option. Phone and tablet show the
  list or selected plan with an explicit return action and restored focus.
  Show the plan title separately from an explicit “Cliente: {nome}” label on
  list cards, selected-plan headers, and approval-history entries.
  Reuse the shared training content view: objective, numbered exercises, grouped
  sets/repetitions/rest, load guidance, and retained equipment labels. Keep
  approved/current/history states explicit, with a separate approval-history
  tab. All-plan search keeps the client name prominent and groups optional
  instructor/date filters behind “Mais filtros”, with a clear reset action.
  Pending review opens in preview mode; editing reuses the authoritative draft
  fields and preserves unsaved changes when returning to preview. Within the
  review workspace, changing selection, reloading, or closing asks before
  discarding unsaved edits. Saving and approval remain distinct actions, and
  approval uses the revision corresponding to the displayed content.
- **AI chat:** Shared client-shell language with clear sender distinction,
  readable message width, persistent input, generating/error/retry states, and
  structured message content when required. Context cues should help without
  crowding the conversation. Reuse chat primitives across onboarding and
  training chat; adaptation adds states to them.
- **Equipment administration:** Use a compact searchable inventory with one
  thumbnail/name group per row, derived active-unit totals and explicit model
  status. Keep creation behind one primary action. A focused details drawer
  groups overview and physical-unit tabs, with separate inventory/operational
  chips, label/private-detail editing and batch addition. Registration uses an
  accessible two-step dialog (full-screen on phone): public information/photo
  and private metadata, then unit quantity/identifier preview. Keep actions
  visible while content scrolls; pending saves disable repeat submission and
  failures preserve the draft. Photo preview must reserve space and provide a
  readable fallback; all fields marked internal remain administrator-only.
- **Instructor equipment:** Keep the search/list beside the selected model's
  units on wide desktops; phone and tablet show one view at a time with an
  explicit return action and restored focus. Use compact unit rows with named
  inventory/operational chips and a warning accent for active units out of
  order. Preserve confirmation and stale-revision recovery for state changes.
  Never show administrator-only metadata in this workspace.
- **Equipment catalog:** Public and client pages share searchable responsive
  image cards and a read-only detail dialog. Use one column on phone, two on
  tablet and three on wide desktops. Keep image areas stable, descriptions
  readable, and active-unit wording distinct from live availability. Missing or
  broken images show the shared equipment fallback without hiding content.
- **Later modules:** Progress sharing evolves in Task 27 into the authenticated
  chronological social feed specified below. Equipment can use local imagery,
  name/type, concise metadata, detail, and total active units.
  Occupancy presents a prominent anonymous count; opt-in named presence is a
  separate view with its own consent state.
- **Social profile:** Task 26 turns “Meu perfil” into an individual social
  profile while retaining ClientShell navigation. Use a responsive profile
  header with a keyboard-accessible picture upload/change control, existing
  name and optional nickname, concise biography, follower/following counts,
  and an owner-only visibility switch. Posts use the established progress-card
  language and open into an accessible detail presentation for like count and
  comments. Clearly distinguish owner-only editing/moderation states from what
  another authenticated client may see. The existing green presence tag remains
  visually and semantically separate from social-profile visibility and updates
  from the saved presence response when consent changes. Follower/following
  counts open an accessible dialog with permitted profile names, avatars and
  profile links, bounded pagination, and loading/empty/error/retry states.
  Private profile graphs remain restricted to their owner and accepted followers;
  list entries respect each viewer's profile access. On phone,
  keep the picture, identity, visibility, follow action, and post navigation
  usable without dense desktop columns. Task 26 must not add a global feed or
  imitate another social network's visual identity.
- **Social feed:** Task 27 redesigns `/progresso` as one restrained,
  single-column, newest-first stream inside ClientShell. Keep the reading
  measure comfortable (approximately 680–760 px on larger screens), let it fill
  the phone content width, and place it beside—not inside—the shared client
  navigation sidebar. Each semantic article has a compact author row with
  keyboard-operable avatar/username profile link, localized timestamp, text,
  optional media, a small “editado” label when applicable, and persistent like
  and comment counts/actions below the content. Counts never depend on hover.
  Private-profile author links open a deliberate unavailable state showing only
  the permitted username and picture/fallback, with Portuguese copy explaining
  that the profile is private.
- **Feed composer:** Place the full composer before the feed heading, in the
  same reading column as the stream. It accepts
  optional text, up to four image previews with individually named remove and
  replace actions, validation, upload progress, and a clear publish action.
  Account privacy determines the audience; the composer has no per-post
  visibility selector. Text or at
  least one image is required. Observe the composer's viewport intersection;
  once it has scrolled away, expose one compact fixed “Criar publicação” action
  near the safe right/bottom edge. It must not cover navigation, cards, or the
  comment action on phone. Activating it scrolls to the original composer and
  focuses its text field; do not mount a second composer or maintain a second
  draft. Hide the compact action whenever the original composer is visible.
- **Feed media:** Reserve each image's persisted aspect ratio before loading to
  prevent layout movement. One image uses the available card width; two use a
  balanced two-column layout; three or four use a compact responsive grid that
  collapses safely on narrow phones. Preserve aspect ratio, constrain media to
  the card, use consistent rounded clipping only for thumbnails, lazy-load
  below-fold media, show skeleton/failure states, and provide an accessible
  name such as “Imagem da publicação de {nome}” when no authored description
  exists. Image activation may open a keyboard-dismissible viewing dialog but
  must not add cropping, filtering, camera capture, or external media URLs.
- **Post detail and comments:** Reuse the feed-card identity/media language at
  the top. Place the comment composer after the post actions and before the
  newest-first comment list. It accepts optional text and at most one image,
  including image-only comments, and has a clearly named “Enviar comentário”
  action. Each semantic comment exposes commenter avatar/username link,
  localized time, content/media, author-only edit/delete affordances, and the
  small “editado” label. Do not indent comments or imply reply threads.
- **Infinite loading:** Use the opaque cursor without replacing already read
  articles or moving focus. An IntersectionObserver sentinel may request the
  next bounded page before the reader reaches the end. Represent loading with
  `aria-busy`, an announced non-blocking loading state, retry on failure, and a
  clear end-of-feed state. Also provide a keyboard/screen-reader-operable
  “Carregar mais publicações” fallback so access does not depend on scrolling
  or observer support. Prevent duplicate requests and de-duplicate posts by
  opaque post ID when pages overlap during concurrent publication.

## Imagery, responsiveness, and accessibility

- Use only project-owned, licensed, or explicitly approved local imagery.
  Fitness photography may support entry, client home, equipment, and selected
  empty/header states. Never reuse Strive assets or rely on random external
  image URLs. Content and actions work when an image is absent. Health forms
  and dense admin tables should not gain decorative imagery.
- Check representative phone, tablet, and desktop layouts for every UI task.
  Client flows must avoid ordinary horizontal scrolling and keep touch targets,
  actions, inputs, and navigation usable. DEC-16 defines the exact formal test
  viewports for personal-use MVP verification.
- Preserve semantic headings/landmarks, labels, keyboard access, visible
  focus, screen-reader-compatible controls, validation text, readable sizes,
  disabled states, and adequate text/control contrast. Recheck RNF02/RNF03
  whenever layouts change.

### Social-feed research basis

- Follow the W3C feed semantics as progressive enhancement: a named feed of
  semantic articles, stable focus, and `aria-busy` while dynamically appending
  content. The W3C example is illustrative rather than a production template,
  so test real keyboard and assistive-technology behavior and prefer native
  HTML where it is clearer:
  <https://www.w3.org/WAI/ARIA/apg/patterns/feed/examples/feed/>.
- Use IntersectionObserver for composer visibility and the page sentinel
  because it observes viewport intersection asynchronously and is intended for
  lazy loading/infinite scrolling without continuous main-thread geometry
  polling: <https://developer.mozilla.org/en-US/docs/Web/API/Intersection_Observer_API>.
- Constrain responsive images, preserve aspect ratio, supply stored width and
  height to reserve space, and lazy-load below-fold media following:
  <https://web.dev/learn/design/responsive-images>.
- Keep visible focus and generous touch targets. WCAG 2.2 requires at least a
  24×24 CSS-pixel target or sufficient spacing at Level AA; this design system
  should continue targeting approximately 44–48 px for primary icon/FAB actions:
  <https://www.w3.org/TR/wcag/#target-size-minimum>.

## Reuse and verification

Task 08 creates the theme, shared UI primitives, ClientShell/AdminShell, and
retroactively restyles the frontend delivered by Tasks 01–07 while preserving
their behavior and API contracts. Future UI tasks must inspect and reuse these
pieces; a genuinely new pattern should be added to the shared system with its
states documented here. Task 18 performs a final MVP visual/accessibility
pass after the major screens are implemented; Task 19 verifies the integrated
MVP. Design work alone does not satisfy RF/CA or formal RNF criteria.

The Keycloak `academia` theme is a later, cross-cutting authentication
presentation integration. It does not retroactively change Task 08 or the
authentication/provisioning task scopes, and it must preserve the existing OIDC
and Keycloak security behavior.

## Client/instructor visual refinement (2026-09-27)

The client and instructor sidebar shells scope a presentation theme derived
from the existing MUI theme. Preserve ink/chalk/coral, system fonts, original
menus and area-switch behavior. Use consistent outline SVG icons, quiet tinted
active navigation with a visible edge, a labeled area, a separated account
footer, and a stable reading canvas. Scope typography/card/tab refinements to
these areas so administrative and Keycloak surfaces retain their design.
Page headers use a compact eyebrow, readable title, description and a divider;
empty states use a quiet bordered surface. No decorative photographic assets,
new destinations or application capabilities are introduced by this redesign.

Client content keeps the existing actions in place: current and draft plans
have distinct accent borders, exercise blocks keep sets/repetitions/rest
together, and health forms use numbered section headers without changing
completion gates. Chats use quiet sender-specific bubbles and a bordered
sticky composer. Social cards group identity and time above content, with
persistent actions below a divider; use shared outline icons instead of emoji.

Instructor client search uses a bordered filter area followed by the client
list and focused workspace on wide screens; they stack on smaller screens,
retaining the existing focus-on-selection behavior. Show onboarding and training
states as named chips and keep the responsible instructor visible. Plan lists
retain their existing preview/edit/history controls with clearer selected
surfaces, client identity, objective and grouped exercise details.

## Administrative dashboard refinement (2026-09-27)

AdminShell now reuses the same authenticated sidebar, typography, cards, icons
and mobile drawer as the client/instructor areas. Its navigation contains the
existing dashboard, facial access, equipment and moderation destinations. The
administrative role has its own menu and does not inherit a client/instructor
area switch. This extends the earlier visual refinement to administration;
Keycloak presentation is unchanged.

The dashboard groups the existing overview, client directory and instructor
directory into accessible tabs. Existing aggregate indicators stay independent
on failure. Weekly attendance uses proportional decorative bars alongside exact
counts and week labels, retaining the distinction between entries and people.

Administrative person directories use focused create/edit dialogs through
`ManagementDialog`: full-screen on phones, bounded width on larger screens,
scrollable fields and persistent actions. Keep feedback inside the active dialog,
group identity/contact, address and access controls, and preserve existing facial
verification gates. Closing a registration retains ordinary local field drafts
but resets the staged facial proof; explain the recheck in the form.
