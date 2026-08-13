# Weekly live validation

The repository has two complementary verification boundaries:

- every pull request runs the complete offline simulator and contract suite;
- one scheduled GitHub Actions workflow runs a bounded MCP smoke scenario
  against two authorized LinkedIn test accounts.

The live workflow is deliberately separate from `pytest`. It runs every Monday
and can also be started with `workflow_dispatch`. Pull requests, forks, and
ordinary pushes cannot invoke it.

## AWS execution model

LinkedIn authentication lives in persistent Chromium profiles. The profiles
are used directly from a dedicated encrypted gp3 EBS volume and are never
copied into GitHub, S3, Actions artifacts, caches, fixtures, or secrets.

```text
GitHub schedule -> OIDC role -> start EC2 -> SSM command -> live MCP suite
                                      |              |
                                      |              +-> sanitized status -> GitHub artifact/badges
                                      +-> encrypted EBS -> two Chromium profiles

                       always stop EC2 <- GitHub cleanup + 3-hour watchdog
```

GitHub uses OpenID Connect to receive short-lived, repository-bound AWS
credentials. The EC2 instance has no inbound security-group rules and accepts
commands only through AWS Systems Manager. The workflow checks out the exact
scheduled `main` revision on EC2, runs it as an unprivileged `linkedin-live`
user, returns a size-bounded sanitized archive through Systems Manager, and
stops the instance even when validation fails.

The EBS volume remains attached while the instance is stopped. CloudFormation
also retains it if the stack or instance is deleted. The root disk contains no
authentication state and can be replaced. AWS charges for the retained EBS
volume continuously and for EC2 only while it is running.

## Closed-loop scenario

The workflow starts two isolated MCP runtimes, each with its own account ID,
profile path, runtime lock, loopback port, and browser context. Calls are serial,
globally delayed by five seconds, and also pass through each server's own
navigation pacer.

| Phase | Account A | Account B |
| --- | --- | --- |
| Session | Runtime, capability, and authenticated-session checks | Authenticated-session check |
| Research | Jobs, people, companies, connections, and invitation inventories | Reads Account A's profile |
| Post loop | Publishes one clearly labeled weekly test post; searches and reads it back | Adds one top-level test comment and one Like reaction |
| Discussion | Reads the exact comment back | Prepares and executes the comment and reaction |
| Message loop | Sends one uniquely marked one-to-one test message | Searches the conversation and reads the exact message back |

All 25 repeatable public tools are required to pass. The six invitation mutation
tools remain present in the product but are marked `simulator` in weekly status:

- `linkedin.invitations.send.prepare` and `.execute`;
- `linkedin.invitations.accept.prepare` and `.execute`; and
- `linkedin.invitations.ignore.prepare` and `.execute`.

Changing the relationship between the two accounts would break the stable
messaging loop, so these actions remain covered by the full offline simulator
on every pull request instead.

## Safety contract

- The live client has a hard-coded execute allowlist containing only post
  creation, post comment, post reaction, and message execution.
- The server receives no invitation mutation scopes in the live runtime.
- Every write still uses the server's immutable prepare, preview, payload hash,
  idempotency, revalidation, and visible postcondition contract.
- A failed or uncertain execute is never retried. Dependent steps are skipped.
- Post-search and message-readback retries are read-only, bounded, and only
  check the exact newly created marker.
- Collections return at most two disjoint cursor pages per weekly smoke run.
  A remaining cursor is reported as the suite's safety bound, not as collection
  completion. Full collection acceptance still follows
  [the collection verification process](COLLECTION_VERIFICATION_PROCESS.md).
- Raw MCP results, LinkedIn content, names, profile URLs, DOM, screenshots,
  traces, cookies, and browser state are not returned to GitHub.
- The AWS role can operate only the exact EC2 instance and the standard
  `AWS-RunShellScript` document. It cannot create infrastructure or read EBS.
- A systemd watchdog requests an EC2 stop three hours after every boot if the
  GitHub cleanup job is interrupted.

Only a sanitized report leaves EC2. It contains the run ID, timestamps,
per-tool state, call count, duration, and a fixed non-personal detail string.
The closed loop intentionally creates one labeled post, comment, reaction, and
message per week. It does not attempt cleanup because the server exposes no
post, comment, or message deletion capability.

## Provision AWS once

The checked-in CloudFormation template creates a dedicated VPC, an outbound-only
EC2 worker, the encrypted retained EBS volume, the Systems Manager instance
role, the repository-bound GitHub OIDC role, and the shutdown watchdog. It does
not create access keys or store LinkedIn credentials.

Deploy in the chosen AWS region, for example Mumbai:

```bash
GITHUB_OIDC_SUBJECT_PREFIX="$(
  gh api repos/prakharagarwal-dev/linkedin-mcp-server/actions/oidc/customization/sub \
    --jq .sub_claim_prefix
)"

aws cloudformation deploy \
  --stack-name linkedin-mcp-live \
  --region ap-south-1 \
  --template-file infra/aws-live-validation/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOidcSubjectPrefix="$GITHUB_OIDC_SUBJECT_PREFIX" \
    GitHubEnvironmentName=linkedin-live
```

Use the exact prefix returned by GitHub. Repositories created after July 15,
2026 use an immutable prefix containing owner and repository IDs; older
name-only trust policies do not match those tokens. See GitHub's
[OIDC subject reference](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims).

An AWS account can have only one GitHub Actions OIDC provider. If one already
exists, pass its ARN instead of asking this stack to create another:

```bash
aws cloudformation deploy \
  --stack-name linkedin-mcp-live \
  --region ap-south-1 \
  --template-file infra/aws-live-validation/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    GitHubOidcSubjectPrefix="$GITHUB_OIDC_SUBJECT_PREFIX" \
    GitHubEnvironmentName=linkedin-live \
    ExistingGitHubOidcProviderArn=arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com
```

The default worker is `m7i-flex.large` with a 24 GiB encrypted root disk and a
50 GiB encrypted gp3 profile volume. The data volume has both `Retain` deletion
and update-replacement policies. Confirm that the volume is no longer needed
before deleting it manually.

## Connect GitHub once

Create a GitHub Environment named `linkedin-live`, restrict it to `main`, and
copy the CloudFormation outputs into environment variables:

| Variable | CloudFormation output or value |
| --- | --- |
| `AWS_LIVE_RUNNER_ACCOUNT_ID` | `AwsAccountId` |
| `AWS_LIVE_RUNNER_REGION` | `AwsRegion` |
| `AWS_LIVE_RUNNER_ROLE_ARN` | `GitHubActionsRoleArn` |
| `AWS_LIVE_RUNNER_INSTANCE_ID` | `InstanceId` |
| `LINKEDIN_LIVE_ACCOUNT_A_SLUG` | Public `/in/...` slug for Account A |
| `LINKEDIN_LIVE_ACCOUNT_B_SLUG` | Public `/in/...` slug for Account B |
| `LINKEDIN_LIVE_ACCOUNT_A_PROFILE_PATH` | `AccountAProfilePath` |
| `LINKEDIN_LIVE_ACCOUNT_B_PROFILE_PATH` | `AccountBProfilePath` |

These values are identifiers and paths, not secrets. The workflow contains no
AWS access key, LinkedIn password, cookie, or browser storage state.

## Authenticate the profiles once

Start the instance and wait until Systems Manager reports it online. Start the
private desktop service with `AWS-RunShellScript`, then create an SSM port
forward from local port 6080 to remote port 6080:

```bash
aws ssm start-session \
  --region ap-south-1 \
  --target i-0123456789abcdef0 \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["6080"],"localPortNumber":["6080"]}'
```

Open `http://127.0.0.1:6080/vnc.html?autoconnect=true`. Through a separate SSM
Run Command, run `linkedin-mcp profile create` and then `linkedin-mcp login` as
the `linkedin-live` user with `DISPLAY=:99` and the corresponding EBS profile
path. Complete LinkedIn login and any checkpoint visibly. Repeat for Account B.

Keep the two profile directories owned by `linkedin-live`, mode `0700`, and
outside the repository checkout. Stop the desktop service and EC2 when login is
complete. Routine weekly runs reuse those profiles without passwords. If
LinkedIn expires a session or displays a checkpoint, validation fails safely
until that profile is reauthenticated through the same private desktop.

## Status publishing

The validation job uploads only the sanitized report and generated Shields
endpoint JSON. A separate GitHub-hosted job publishes those JSON files to the
generated `live-status` branch when the workflow runs from `main`. The README's
overall workflow badge and per-tool badges then reflect the latest run.

The repository's Actions policy must allow the workflow's scoped
`contents: write` permission for that generated branch. No source branch is
modified by the status job.

## Running manually

Use **Actions → Weekly live validation → Run workflow**. A green run means all
25 repeatable tools passed their exact scenario. `blocked` usually means a
profile needs reauthentication or LinkedIn displayed a checkpoint; `failed`
means a tool or postcondition did not satisfy the current contract.

Do not rerun a failed write blindly. Inspect the safe result first,
reauthenticate when required, and diagnose any current-UI drift before the next
bounded run. EC2-local diagnostic logs remain on the encrypted EBS volume under
`/var/lib/linkedin-mcp-live/logs`; they are never uploaded automatically.
