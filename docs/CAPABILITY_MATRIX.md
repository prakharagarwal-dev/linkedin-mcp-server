# Capability Reference

The public MCP surface is task-specific. It does not expose generic browser,
navigation, selector, JavaScript, click, or network tools.

All domain tools require `context_id` and `request_id`. Collection tools also
accept `page_size` (1–100) and an optional cursor returned by the immediately
preceding page.

## Jobs

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.jobs.search` | Query, location, freshness, sort, distance, workplace, experience, employment type, locations, companies, industries, functions, titles, benefits, commitments, Easy Apply, verification, applicant count, network, and fair-chance filters | Typed job summaries, coverage, pagination, and evidence |
| `linkedin.jobs.get` | Numeric job ID | Expanded visible description, header metadata, company, application method, hiring team, coverage, and evidence |

## People

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.people.search` | Query; connection degree; hiring status/title; location; current/past company; connections/followers of; school; industry; language; service; first name; last name; title; company; and school keywords | Typed member summaries, coverage, pagination, and evidence |
| `linkedin.people.get` | Profile slug and one or more section selectors | Visible profile data, selected member-owned sections, coverage, and field evidence |

Profile section selectors are `all`, `overview`, `about`, `experience`,
`education`, `licenses-certifications`, `projects`, `volunteering`, `skills`,
`interests`, `featured`, `courses`, `honors-awards`, `languages`,
`organizations`, `publications`, `patents`, `recommendations`, and
`test-scores`.

## Companies

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.companies.search` | Query, headquarters locations, industries, company sizes, available jobs, and first-degree connection presence | Typed company summaries, coverage, pagination, and evidence |
| `linkedin.companies.get` | Company slug | Fixed Overview and About read with identity, description, website, industry, size, associated-member/follower counts, headquarters, type, founding year, specialties, coverage, and evidence |

## Posts

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.posts.search` | Query, sort, date, content type, source member/company, relationship, mentioned member/company, author industry/company, and author keywords | Typed post summaries, explicit unsupported-card counts, coverage, pagination, and evidence |
| `linkedin.posts.get` | Activity, share, or UGC post reference | Expanded post, author, text, media, links, mentions, hashtags, poll/repost data, engagement, coverage, and evidence |
| `linkedin.posts.comments.list` | Post reference, sort, page size, and bounded replies per root | Typed root comments and visible nested replies with pagination and coverage |
| `linkedin.posts.create` | Typed content, audience, comment control, optional group/collaborators/brand partnership/schedule | One terminal action result plus evidence |
| `linkedin.posts.comment` | Post reference, text, mentions, or one photo/GIF attachment | One top-level comment action result, verified only by exactly one new stable comment reference matching the requested payload, with evidence |
| `linkedin.posts.react` | Post reference and `none`, `like`, `celebrate`, `support`, `love`, `insightful`, or `funny` | Verified reaction state, failure, or uncertainty plus evidence |

Post creation modes are `text`, `images`, `video`, `document`, `poll`,
`celebration`, `event`, `hiring`, and `expert_request`. The server does not
publish as a company Page, create nested comment replies, or react to comments.

## Network

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.connections.list` | Sort by recently added, first name, or last name | Established first-degree connections with pagination and coverage |
| `linkedin.connections.search` | Query and the People filters applicable to established connections | First-degree member matches with pagination and coverage |
| `linkedin.invitations.list` | Received/sent direction and a visible invitation filter | Typed invitation entities with reconciled coverage and pagination |
| `linkedin.invitations.send` | Exact profile slug and optional note up to 200 characters | Verified pending state, LinkedIn failure, or uncertainty plus evidence |
| `linkedin.invitations.accept` | Exact profile slug | Verified connected state, failure, or uncertainty plus evidence |
| `linkedin.invitations.ignore` | Exact profile slug | Verified invitation removal, failure, or uncertainty plus evidence |

Received invitation filters are `all`, `focused`, `other`, `verified`,
`same_company`, `same_school`, and `mutual_connections`. Sent invitations use
the visible `people` view. LinkedIn conditionally omits controls for empty
invitation views. In that state, coverage leaves `advertised_count` null, names
the affected filters in `unadvertised_empty_views`, and reports completion only
after the current visible surface independently proves the selected inventory
empty.

## Messaging

| Tool | Input | Result |
| --- | --- | --- |
| `linkedin.messaging.search` | Query, Focused/Other/Archived/Spam category, and Jobs/Unread/Connections/Starred/InMail filter | Conversation summaries with pagination and coverage |
| `linkedin.messaging.conversation.get` | Exactly one profile slug, conversation ID, or returned conversation reference; bounded message count | Visible incoming/outgoing history, attachments, reply metadata, edits, reactions, and completeness coverage |
| `linkedin.messaging.send` | Exactly one conversation target; text/files/GIF; optional exact message reply target | One terminal send result plus evidence |

Messaging is limited to unambiguous visible one-to-one conversations. Group
messages, paid InMail sends, voice messages, edits, deletion, forwarding, and
message reactions are outside the current contract.

## Operational tools

| Tool | Purpose |
| --- | --- |
| `linkedin.server.status` | Read safe shared-runtime, queue, and active-operation state |
| `linkedin.capabilities.list` | Discover registered domain tools, versions, effects, and required surfaces |
| `linkedin.session.status` | Read safe browser setup and LinkedIn authentication state |

## Result contract

Reads return typed data, bounded coverage, source metadata, and pagination
where applicable. Account-changing tools return exactly one terminal outcome:

- `verified`: the exact visible postcondition was observed;
- `failed`: LinkedIn visibly rejected the action or retained the unchanged
  state; or
- `uncertain`: the action may have happened, but the visible postcondition
  could not be proved.

An uncertain action should be reviewed before any retry.
