# LinkedIn Visible-Feature Matrix

**Matrix version:** `2026-08-05.2`

This matrix records the visible LinkedIn controls and outputs inspected for the
configured authorized member account. It is evidence for capability acceptance,
not a claim about every LinkedIn account, geography, subscription, or experiment.

Feature status values:

- `supported`: represented by a typed contract, fixture coverage, and a
  fail-closed page adapter;
- `not_available_to_account`: inspected but not visible to the configured
  validation account;
- `outside_named_capability`: visible but belongs to a different explicitly
  authorized capability.

Every accepted family below has a typed, fixture-validated contract. The M11-M17
families also completed a low-volume authenticated installed-MCP inventory on
2026-07-24. A live draft-preparation pass does not authorize or imply a real
mutation.

The current testing-program classification is `mock_verified` for every
family. Historical authenticated observations remain recorded as context but
do not upgrade this classification.

## Accepted capability families

| Capability family | Contract version | Current evidence | Verification |
| --- | --- | --- | --- |
| Jobs search | `linkedin.jobs.search` `2.0.0` | Current virtualized cards, optional keywords, every visible filter family, exact named-facet resolution, recommendation-safe empty results, anonymous postings, evidence, and replay | `mock_verified` + read-only live acceptance |
| Job detail | `linkedin.jobs.get` `2.0.0` | Current primary-card anchors, optional company identity, application method, single-link composite hiring-team cards with separately typed fields, fully expanded JD, scoped evidence, and replay | `mock_verified` + read-only live acceptance |
| People search | `linkedin.people.search` `2.0.0` | Every current account-visible People filter, delayed/anonymous rendering, trailing-hyphen slugs, and shared cursor contract is fixture-covered | `mock_verified` + read-only live acceptance |
| Member profile | `linkedin.people.get` `1.1.1` | Complete/selective sections, exact evidence resources, requested/returned coverage, genuine trailing-hyphen public slugs, nested self-introduction cards, recommendation/guidance exclusion, semantic company/school summaries, current roleless detail collections and experience cards, exact skill identity, and clean About text | `mock_verified` + read-only live acceptance |
| Company search | `linkedin.companies.search` `2.0.0` | Complete current Company-search surface: keywords, headquarters, industry, all eight company-size buckets, job-listing and first-degree-connection flags, named-facet resolution, delayed rendering, evidence, and cursor contracts | `mock_verified` |
| Company profile | `linkedin.companies.get` `2.0.0` | Fixed exact Overview-plus-About read with structured visible fields and two immutable page sources | `mock_verified` |
| Post search | `linkedin.posts.search` `2.0.0` | Declared content facets, delayed/current card variants, stable references, exact per-card evidence across dynamic rendering, and cursor contract | `mock_verified` + read-only live acceptance |
| Post detail | `linkedin.posts.get` `2.0.0` | Exact activity/share/UGC identity, fully expanded text, scoped links/mentions/hashtags, current text/image/video/live-video/document/link/article/newsletter/event/job/poll variants, viewer reaction and engagement, visibility/header metadata, immutable field evidence, bounded completeness coverage, and two-page repost-original resolution | `mock_verified` + read-only live acceptance |
| Post discussion | `linkedin.posts.comments.list` `1.1.1` | Ordering, cursor-paged top-level comments, delayed expansion including the current `See previous replies` control, flat visually indented parent binding, replies, media, and source retrieval | `mock_verified` + read-only live acceptance |
| Personal post publishing | `linkedin.posts.create.*` `2.0.0` | Nine current personal composer modes, bounded loader settling, unchanged disabled-setting handling, visible publish-success/rejection postconditions, exact nested options, immutable previews, tamper rejection, execution, and replay | `mock_verified` |
| Post/comment engagement | `linkedin.posts.comment.*` and `linkedin.posts.reaction.*` `2.0.0` | Current comment/reply text, external generic reply composer, photo and GIF controls, native discussion aliases, delayed accessible comment-reaction controls, all six reactions, tamper rejection, execution, and replay | `mock_verified` + live mutation/readback acceptance |
| Invitations | List `4.0.0`; send, accept, and ignore `1.0.0` | Latest-layout-only received/sent extraction; bounded live cursor traversal; exact terminal per-view count reconciliation; and the complete currently implemented invitation lifecycle under one namespace, with scoped hash-locked writes and exact-profile postconditions | `mock_verified` + read-only/prepare-only live acceptance |
| Connections | List `2.0.0`; search `2.0.0` | Separate sorted inventory and filtered search of established first-degree connections; the server always binds search to first degree and rejects non-first-degree results | `mock_verified` + read-only live acceptance |
| Messaging | Search, conversation get, message prepare, and execute `2.0.0` | Current recipient/message search criteria and mutually exclusive filters; cursor paging; reverse-virtualized history; exact recipients/replies; current text, file, and KLIPY GIF preparation; reply-aware same-surface postconditions; tamper rejection; and replay | `mock_verified` + read/prepare-only live acceptance |

## Shared collection pagination

All nine LinkedIn search/list contracts accept `page_size` and an opaque
single-use `cursor`. Each output returns a scan ID, returned and cumulative
counts, `has_more`, optional next cursor/expiry, terminal truncation state, and
consistency mode. Cursor state is process-local, expiring, bound
to the account/capability/semantic filters, and capped by server memory and
browser-traversal safety limits. The compatibility names `max_results` and
`max_comments` remain accepted during the transition but are not the canonical
domain-model fields.

Every collection family reports `live_deduplicated` and rescans a bounded live
prefix for continuations. Cursor state stores stable identities already
returned, not captured LinkedIn content. A continuation skips those identities
and returns the next unseen page plus terminal or truncation metadata.

Collection completion is evidence-driven: raw visible identities detect
appended and same-count virtualized progress, and polling idleness alone never
sets `has_more=false`. Count-backed invitation views complete only after exact
reconciliation; collectors without an exact count require independent visible
terminal evidence. Exhausting a private traversal bound reports truncation
rather than silently advertising a complete list.

## `linkedin.people.get` `1.1.1`

The canonical profile overview is always captured for identity. The structured
result and detail navigation follow the requested selector. A selector whose
section is not visible is returned in `unavailable_sections`; a selected detail
page beyond the private server bound is returned in `truncated_sections`.

| Visible/profile feature | Status | Typed behavior and evidence |
| --- | --- | --- |
| Canonical member overview and exact slug identity | `supported` | Always captured; typed introduction fields and exact main-page source |
| All visible member-owned sections | `supported` | `sections: ["all"]` compatibility default; generic loss-preserving entries from both semantic lists and the current roleless detail collection boundary |
| Overview only | `supported` | `overview`; no detail-page navigation |
| About | `supported` | `about`; typed body plus exact field evidence when visible |
| Experience | `supported` | `experience`; typed entries and matching visible detail link. Standalone employment type is retained without inventing an organization or location when the current card does not expose either field; legacy combined organization/employment cards remain supported. |
| Education | `supported` | `education`; typed entries and matching visible detail link |
| Licenses and certifications | `supported` | `licenses-certifications`; generic entries and source |
| Projects | `supported` | `projects`; generic entries, links, and source |
| Volunteer experience | `supported` | `volunteering`; current route/heading aliases normalize to one key |
| Skills | `supported` | `skills`; matching detail navigation and exact skill-card identity from the accessible endorsement control, with generic loss-preserving fallback entries |
| Interests | `supported` | `interests`; matching visible detail navigation |
| Featured | `supported` | `featured`; matching visible detail navigation |
| Courses | `supported` | `courses`; matching visible detail navigation |
| Honors and awards | `supported` | `honors-awards`; route and heading normalize to one key |
| Languages | `supported` | `languages`; generic entries and source |
| Organizations | `supported` | `organizations`; matching visible detail navigation |
| Publications | `supported` | `publications`; matching visible detail navigation |
| Patents | `supported` | `patents`; matching visible detail navigation |
| Recommendations | `supported` | `recommendations`; matching visible detail navigation |
| Test scores | `supported` | `test-scores`; matching visible detail navigation |
| Requested/returned/unavailable coverage | `supported` | Strict enum input and typed coverage tuples |
| Discovered/visited/truncated detail coverage | `supported` | Exact normalized detail keys and private page bound |
| Recommendation rails and owner optimization panels | `outside_named_capability` | Retained only in immutable raw source; `More profiles for you`, Premium-profile exploration, and similar rails are never attributed to the member |
| Hidden/private profile fields | `outside_named_capability` | No private endpoint access or inference |

## Company research (`search 2.0.0`, `profile 2.0.0`)

Company search requires keywords or at least one typed filter. Human-readable
headquarters and industry values resolve through an exact visible choice;
stable facet IDs are the explicit disambiguation path. The profile overview is
always captured for identity, followed by the exact same company's About page.
There is no section selector: each successful get returns exactly these two
sources.

| Visible/company feature | Status | Typed behavior and evidence |
| --- | --- | --- |
| Company keywords/Boolean search | `supported` | Optional bounded query with exact retained result cards |
| Headquarters locations | `supported` | Multiple IDs or exact visible names |
| Industries | `supported` | Multiple IDs or exact visible names |
| Company size | `supported` | All eight current buckets: 1–10, 11–50, 51–200, 201–500, 501–1,000, 1,001–5,000, 5,001–10,000, and 10,001+ |
| Job listings on LinkedIn | `supported` | Boolean `has_job_listings` maps to the visible `Yes` choice |
| Connections | `supported` | Boolean `has_first_degree_connections` maps to the visible `1st` choice |
| Canonical overview and exact slug | `supported` | Always captured as the identity source |
| About and website | `supported` | Typed body/link plus exact source evidence when visible |
| Company size range | `supported` | Dedicated field; never substituted with member count |
| Associated member count | `supported` | Separate visible field; never treated as company size |
| Headquarters, type, founded, specialties | `supported` | Typed visible About values with exact quotes |
| Fixed Overview + About coverage | `supported` | Exactly two visited sources and the fixed returned tuple `overview`, `about` |
| Other Company tabs | `outside_named_capability` | Locations, commitments, products, services, Life, events, and newsletters are not traversed |
| Company-authored posts | `supported_via_posts_search` | Use `linkedin.posts.search` with `author_company_ids` or exact `author_company_names` |
| Company employees | `supported_via_people_search` | Use `linkedin.people.search` with `current_company_ids` or exact `current_company_names` |
| Page administration or company publishing | `outside_named_capability` | Not implemented |

## Post and discussion research (`search 2.0.0`, `comments 1.1.1`, `detail 1.0.0`)

Post search requires keywords or at least one substantive filter. Identity names
resolve through exact visible choices; stable facet IDs are the explicit
disambiguation path. Direct post and discussion reads require stable
`activity:<digits>`, `share:<digits>`, or `ugc-post:<digits>` references
constructed only from visible post URNs/URLs.

| Visible post/discussion feature | Status | Typed behavior and evidence |
| --- | --- | --- |
| Keywords and Boolean search | `supported` | Optional bounded query with exact retained result cards |
| Top-match/latest order | `supported` | `top_match` or `latest` |
| Date posted | `supported` | Any time, past 24 hours, past week, or past month |
| Content type | `supported` | One current visible choice: videos, images, job posts, live videos, or documents |
| From member/company | `supported` | Multiple stable IDs or exact visible names |
| Posted by relationship | `supported` | The configured member, first-degree connections, and/or people the configured member follows |
| Mentioning member/company | `supported` | Multiple stable IDs or exact visible names |
| Author industry/company | `supported` | Multiple stable IDs or exact visible names |
| Author Keywords | `supported` | Exact visible title text through LinkedIn's current Author Keywords field |
| Stable post identity | `supported` | Activity, Share, and UGC-post references remain distinct; canonical URL rebuilt server-side |
| Non-addressable content cards | `supported` | Trusted LinkedIn article/newsletter Copy links without a stable post identifier are quarantined, never guessed |
| Exact visible author | `supported` | Typed member/company identity and canonical author URL |
| Post body, time, edit, and visibility | `supported` | Retained text and explicit visible state |
| Attachments and content type | `supported` | Visible image, video, document, article, event, job, poll, newsletter, celebration, text, or other representation |
| Links, mentions, and hashtags | `supported` | Exact visible labels and URLs plus body hashtags |
| Reaction, comment, and repost counts | `supported` | Human-readable visible count text, not inferred numbers |
| Relevant/recent comment order | `supported` | `most_relevant` or `most_recent` |
| Top-level comments and nested replies | `supported` | Stable comment refs with exact parent binding |
| Comment author, body, time, edit, counts | `supported` | Exact visible observation fields |
| Photo/GIF-only comments and replies | `supported` | Optional text plus typed attachment kind, accessible label, visible resource URL when present, and exact accessibility evidence |
| Bounded comment/reply expansion | `supported` | Private expansion bound and explicit visible/returned/truncated coverage |
| Hidden posts, comments, or private endpoints | `outside_named_capability` | No inference or private endpoint access |
| Publishing, comments, replies, or reactions | `outside_named_capability` | Separate M15/M16 write contracts; no read scope grants mutation |

## Personal publishing `2.0.0`

Only the configured personal member can be the actor. Every local file is
resolved below one configured asset root, validated by format/size, hashed at
preparation, included in the immutable payload, and hash-checked again before
browser access during execution.

| Visible personal-composer feature | Status | Typed behavior and evidence |
| --- | --- | --- |
| Text and URL posts | `supported` | Exact text, optional exact URL, and retained/removable link preview |
| Member/Page mentions | `supported` | Exact token and exact visible identity selection |
| Image posts | `supported` | One to twenty GIF/JPEG/JPG/PNG/WebP occurrences, duplicates, alt text, exact member/company tags, crop/aspect, rotate/flip, zoom/straighten, seven filters, and four adjustments |
| Video posts | `supported` | Current desktop video extensions and 75 KB–5 GB bound, optional GIF/JPEG/JPG/PNG/WebP thumbnail, explicit no/automatic/SRT captions, and review option |
| Document posts | `supported` | DOC/DOCX/ODT/PPT/PPTX/PDF/PPSX/ODS, 100 MB bound, and required visible document title |
| Polls | `supported` | Question, two to four unique options, and 1-day/3-day/1-week/2-week duration |
| Celebrations | `supported` | Project launch, work anniversary, new position, education milestone, or certification with one of 22 current templates or a custom image |
| Events | `supported` | Online LinkedIn Live/external-link or in-person event, exact timezone/start/end, description, venue/link, first-degree speakers, and optional cover |
| Hiring | `supported` | Exact existing employer job ID/title; new job creation remains a separate Jobs-domain effect |
| Find an expert | `supported` | Accounting, Coaching & Mentoring, Design, Marketing, or Other; exact visible location and 25–750 character request |
| Audience | `supported` | Anyone, connections only, or one exact visible group |
| Comment control | `supported` | Anyone, connections only, or no one |
| Brand partnership | `supported` | Exact current switch; public audience enforced |
| Collaborators | `supported_if_visible` | Up to five exact member/company identities; public audience enforced; fails closed where the rollout is unavailable |
| Scheduling | `supported` | Timezone-aware 10-minute-to-3-month future time and visible confirmation; LinkedIn does not schedule event, hiring, or expert-request posts |
| Personal actor binding | `supported` | Active slug/name are captured and revalidated before the final action |
| Publication verification | `supported` | A visible LinkedIn success alert and exact View post link are authoritative; a newly visible stable post matching the confirmed marker remains a bounded fallback, and a visible rejection is a verified failure |
| New job creation from Hiring | `outside_named_capability` | Creates a new job entity and requires a separate Jobs-domain effect |
| Articles and newsletters | `outside_named_capability` | Long-form/editor and recurring-publication workflows need separate capabilities |
| Repost/share of an existing post | `outside_named_capability` | Requires an exact source-post target and its own mutation contract |
| Company/Page publishing | `outside_named_capability` | Permanently excluded from this personal-actor capability |

## Personal comments, replies, and reactions `2.0.0`

| Visible engagement feature | Status | Typed behavior and evidence |
| --- | --- | --- |
| Top-level text/link/emoji comment | `supported` | Exact text through one visible comment composer |
| Reply to a comment | `supported` | Explicit stable parent comment reference, exact thread binding including the current flat visually indented layout, one exact Reply-only composer form, and runtime-verified activity-URL to native UGC-discussion mapping |
| Member/Page mention | `supported` | Exact token plus exact visible identity resolution |
| Photo | `supported` | One hash-locked GIF/JPEG/JPG/PNG/WebP upload through the current Share photo chooser |
| GIF picker | `supported` | Exact Search for GIFs/KLIPY query and one unique result image alt label |
| Like, Celebrate, Support, Love, Insightful, Funny | `supported` | Typed reaction states for both posts and comments |
| Remove reaction | `supported` | Explicit `none`; never inferred from a repeated click |
| Set/change/no-op | `supported` | Existing and desired state are both captured, passed through the client approval policy, and revalidated |
| Comment/reply verification | `supported` | Exactly one new stable reference must match actor and parent; text and GIF label match exactly, while a photo additionally requires the prepared file hash and visible photo type |
| Reaction verification | `supported` | The bounded accessible reaction surface must load before preparation/execution; final visible state must equal the confirmed desired state, while a missing pre-click control is a verified non-mutation rather than an uncertain action |
| Comment as a LinkedIn Page | `outside_named_capability` | Different actor and authorization contract; personal actor is mandatory |
| Edit/delete/pin/report/repost a comment | `outside_named_capability` | Materially different effects requiring separate scopes and payloads |

## M17 Jobs parity audit

LinkedIn search-result counts are approximate. The server reports only bounded
cards actually captured and never adopts LinkedIn's advertised 1,000-result
limit as an enumeration guarantee.

| Current Jobs feature | Status | Contract decision |
| --- | --- | --- |
| Keyword, Boolean, and conversational query text | `supported` | Optional exact bounded query string; an omitted query supports filter/location-led discovery |
| Location and stable geography | `supported` | Visible location text or numeric geo ID |
| Distance | `supported` | 0, 5, 10, 25, 50, or 100 miles |
| Date posted | `supported` | Any time by default or an explicit 24-hour/week/month window |
| Sort | `supported` | Most relevant or most recent |
| Workplace type | `supported` | On-site, remote, hybrid |
| Experience and employment type | `supported` | Every current visible choice, including employment type `Other` |
| Company, industry, job function, and normalized title | `supported` | Stable IDs or exact visible labels |
| Easy Apply, verified, under 10 applicants, in network | `supported` | Independent typed flags |
| Benefits and company commitments | `supported` | Every inspected standard choice |
| Fair Chance Employer | `supported` | Typed account/region-dependent flag that fails closed if absent |
| Virtualized result cards and continuation | `supported` | Every current card shell is hydrated by stable numeric ID; cursor pages are deduplicated and filter-bound |
| Empty query results | `supported` | A genuine zero-result state completes empty; LinkedIn's later recommendation rail is never returned as a match |
| Anonymous/confidential postings | `supported` | Missing company identity remains `null`; title, location, workplace, and exact evidence are preserved |
| Full visible job description and metadata | `supported` | Direct job ID, fully expanded description, current header fields, optional company identity, and exact scoped evidence |
| Application method and hiring team | `supported` | Read-only `easy_apply`, `external`, or `unavailable` classification plus visible hiring-team identities |
| Save job and job alerts | `outside_named_capability` | Account-changing effects, not search/read filters |
| Submit Easy Apply or external Apply | `outside_named_capability` | Separate application workflow and authorization boundary |
| Premium fit/applicant insights | `outside_named_capability` | Subscription-dependent derived product, not source job detail |

## M17 People parity audit

| Current People feature | Status | Contract decision |
| --- | --- | --- |
| Keyword, Boolean, and conversational text | `supported` | Exact bounded query; LinkedIn performs semantic matching |
| Connection degree | `supported` | First, second, and third-plus |
| Actively hiring | `supported` | Any job title or exact visible hiring-title choices |
| Locations and current companies | `supported` | Stable IDs or exact visible picker labels |
| Connections of and Followers of | `supported` | Stable member IDs or exact visible member names |
| Past companies, schools, and industries | `supported` | Stable IDs or exact visible picker labels |
| Profile languages | `supported` | Stable codes or exact current visible labels |
| Service categories | `supported` | Stable IDs or exact visible picker labels |
| First name, last name, title, company, and school | `supported` | Exact current visible keyword fields |
| Talks about and Open to volunteering | `not_available_to_account` | Not present in the authenticated 2026-07-29 filter panel and therefore not exposed by the current typed contract |
| Anonymous restricted results | `supported` | Visible `LinkedIn Member` cards without `/in/` identities are counted in coverage and never invented as profiles |
| Complete/selective profile reads | `supported` | M11 overview plus every registered member-owned detail section |
| Follow, connect, or message from a result | `outside_named_capability` | Separate account-changing capabilities; search never mutates |
| Approximate result counter | `outside_named_capability` | Not represented as an exact total |

## Invitation and Connections parity audit

| Current Connections feature | Status | Contract decision |
| --- | --- | --- |
| Received filters | `supported` | Exact current `Focused`, `Other`, `Verified`, `Mutual Connections`, `Your Company`, and `Your School` controls and advertised counts |
| Received `all` | `supported` | Server-defined deduplicated union of all six current views; LinkedIn exposes no reliable current All control |
| Sent filter | `supported` | Exact current `People (N)` control; omitting the filter dynamically selects People |
| Person invitations | `supported` | Stable person identity, headline, note, relationship context, time, and available actions |
| Company and school invitations | `supported` | Typed primary entity plus visible inviter when present |
| Group, event, and newsletter invitations | `supported` | Typed entity URL/slug/name and invitation family |
| Newly introduced invitation surfaces | `supported` | Loss-preserving `other` entity/type with exact visible evidence |
| Invitation completion | `supported` | Single views reconcile their exact advertised count; `all` reconciles every view, then reports membership, overlap, and unique union counts; idle, bottom, loader, and end copy never prove completion |
| Invitation pagination | `supported` | Opaque filter-bound single-use cursors rescan a bounded live prefix, suppress already returned invitation identities, permit page-size changes, refresh expiry on continuation, and claim terminal completion only after exact selected-view reconciliation |
| Neighboring recommendations | `supported` | Excluded from invitations and counted separately |
| Current first-degree connections | `supported` | `linkedin.connections.list` cursor-pages the visible inventory without mixing search semantics |
| Recently added/first name/last name order | `supported` | Typed visible sorting |
| Established-connection search | `supported` | `linkedin.connections.search` follows the visible Search with filters entry, always submits the first-degree filter, exposes every applicable non-degree People filter, and rejects any result not visibly marked first-degree |
| Broad People discovery | `supported` | `linkedin.people.search` owns first-, second-, and third-plus-degree discovery and exposes the explicit connection-degree filter |
| Search pagination | `supported` | Opaque filter-bound cursor rescans a bounded People-search prefix and suppresses already returned profile identities |
| Invite with optional note | `supported` | Preparation binds LinkedIn's current `Invite {name} to connect` button to the exact profile, waits for asynchronous action hydration, and validates both current dialogs plus exact note/counter/actionability without sending. After the hash-locked, client-authorized Send click, execution performs exactly one fresh exact-profile check: visible Pending is verified success and Connect is verified LinkedIn failure. An unreadable, identity-mismatched, or otherwise ambiguous fresh profile is uncertain. No toast parsing, post-click polling, or Sent-list reconciliation is part of this capability. |
| Accept invitation | `supported` | Exact member-profile request controls, hash-locked client approval policy, and fresh-profile first-degree postcondition |
| Ignore incoming invitation | `supported` | Separate `linkedin.invitations.ignore.prepare/execute` action with its own scope, paired exact-profile controls, hash-locked client approval policy, and fresh-profile removal-without-connection postcondition |
| Report incoming invitation | `outside_named_capability` | Distinct moderation target and effect |
| Withdraw sent invitation | `outside_named_capability` | Distinct destructive effect |
| Reply to invitation message | `outside_named_capability` | Distinct pre-connection messaging target and effect |
| Remove a connection | `outside_named_capability` | Distinct destructive relationship effect |

## Current Messaging contract

All four Messaging capabilities are version `2.0.0`. Opening a conversation
may mark it seen. Search returns conversation summaries only; there is no
separate inbox-list tool. GIF selection is modeled separately because the
current desktop UI sends the selected GIF immediately.

| Current desktop Messaging feature | Status | Contract decision |
| --- | --- | --- |
| Search by recipient or message keyword | `supported` | One current `Search messages` query, submitted explicitly; at least one query/category/filter criterion is required |
| Focused/Other/Archived/Spam categories | `supported` | Exact current category dropdown; omitted category resolves deterministically to Focused |
| Jobs/Unread/Connections/InMail/Starred filters | `supported` | Exact current top-level filter pills; LinkedIn makes them mutually exclusive, so the contract accepts zero or one |
| Cursor pagination | `supported` | Process-local, expiring, single-use, query/category/filter-bound continuations with live deduplication |
| Link-backed and linkless conversation cards | `supported` | Stable thread ID when visible; otherwise a bounded process-local reference replays the exact search context and exact participant |
| Reverse-virtualized history | `supported` | Bounded older-message traversal tolerates delayed batches, deduplicates moving windows, and returns explicit completeness, truncation, rounds, and stop reason |
| Incoming/outgoing/system text | `supported` | Explicit current UI direction wins; grouped senderless bubbles inherit the prior non-system direction |
| Visible replies, edits, and reactions | `supported` | Reply sender/body, Edited state, and visible reaction summaries are returned with the exact message evidence |
| Visible document/image/video/GIF metadata | `supported` | Kind, name/accessible label, visible resource URL when present, and exact source |
| Plain text, URL, emoji, and reply send | `supported` | Exact 8,000-character-bounded text; an optional message reference binds the hover-only Reply control before Send |
| Current desktop general files | `supported` | AI, PSD, PDF, DOC/DOCX, PPT/PPTX, PPS/PPSX, XLS/XLSX, TXT, EML, MOV, and MP4 |
| Current desktop images | `supported` | BMP, GIF, HEIC/HEIF, JPEG/JPG, PNG, TIF/TIFF, and WEBP |
| Combined attachment size | `supported` | Up to twenty unique relative asset references, hash-locked and capped at 20 MB total |
| KLIPY GIF search/send | `supported` | Exact search query and exact current result title; selecting the confirmed result is the guarded final action |
| One-to-one recipient identity | `supported` | Exact hash-locked thread and name; profile targets search the smallest profile-card ancestor containing the exact heading and first-degree marker, then fall back to the visually nearest visible Message action on that already-validated profile. A button must open the smallest recipient-named composer pane in place; a visible Messaging link is followed in the same operation page to an exact-name/profile thread |
| Send postcondition | `supported` | The same visible surface must gain exactly one matching outgoing bubble; text/file sends must also clear the composer. A reply must quote the exact selected message evidence. A missing reply binding, disappearing surface, or unverifiable result is never reported as success |
| Group chats | `outside_named_capability` | Multiple recipients require a different target and effect contract |
| Paid InMail | `outside_named_capability` | Subject, credits, and non-connection recipient require a separate paid effect |
| Message requests/invitation replies | `outside_named_capability` | Different target state and permissions |
| Voice messages | `outside_named_capability` | Mobile-only surface is not authorized |
| Edit/delete/react/forward/star/report/archive | `outside_named_capability` | Distinct mutations requiring separate scopes and payloads |
| Read/delivery receipts or hidden/deleted history | `outside_named_capability` | Never inferred from unavailable state |

## Inventory references and mutation boundary

The audit used the previously accepted account fixtures/live evidence plus
current first-party help documentation:

- [Filter and sort job search results](https://www.linkedin.com/help/linkedin/answer/a507441/filter-and-sort-job-search-results)
- [Search for jobs](https://www.linkedin.com/help/linkedin/answer/a511260/searching-for-jobs-on-linkedin)
- [Search for people](https://www.linkedin.com/help/linkedin/answer/a525054)
- [Accept, ignore, or report invitations](https://www.linkedin.com/help/linkedin/answer/a540852)
- [Search and filter messages](https://www.linkedin.com/help/linkedin/answer/a542831)
- [Attach files to messages](https://www.linkedin.com/help/linkedin/answer/a567264/anfugen-von-dateien-und-bildern-an-linkedin-nachrichten?lang=en)
- [Send a photo, video, GIF, or emoji](https://www.linkedin.com/help/linkedin/answer/a563259)
- [Comment and reply](https://www.linkedin.com/help/linkedin/answer/a524166/comment-on-posts-reply-to-a-comment-pin-and-unpin-a-comment)
- [Like, unlike, and react](https://www.linkedin.com/help/linkedin/answer/a522684/like-unlike-and-react-to-posts-or-comments)
- [Turn off or limit comments](https://www.linkedin.com/help/linkedin/answer/a523384/disable-re-enable-and-limit-comments-on-posts)

M11-M17 completed the opt-in installed-stdio inventory on 2026-07-24 under the
legacy local-approval design. All read and preparation outputs used readable
immutable source resources, and the audit performed zero LinkedIn writes.
Version `0.4.0` replaced that gate with MCP client approval: every execute
schema carries the canonical human-readable preview, and fixture, repository,
and protocol tests reject altered hashes or previews before an action attempt.
Current clients may use interactive confirmation or an explicit durable
per-tool approval. Live smoke tests remain non-mutating by intentionally
altering the preview.
