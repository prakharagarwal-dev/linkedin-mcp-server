# Security Policy

## Supported versions

Security fixes are applied to the latest release and `main`.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Earlier versions | No |

## Report a vulnerability privately

Do not open a public issue for a vulnerability. Use
[GitHub's private vulnerability reporting](https://github.com/prakharagarwal-dev/linkedin-mcp-server/security/advisories/new).
If that channel is unavailable, email `prakharagarwal3031@gmail.com` with the
subject `linkedin-mcp-server security report`.

Include the affected version, impact, smallest synthetic reproduction, and any
suggested mitigation. Do not send LinkedIn credentials, cookies, access tokens,
browser-profile archives, private messages, real member data, raw authenticated
DOM, or other sensitive account content. Redact local paths and identifiers.

You should receive an acknowledgement within seven days. Please allow time for
investigation and a coordinated fix before public disclosure.

## Scope

Examples of in-scope security issues include:

- target-identity or visible-postcondition bypass;
- attachment-root escape or unsafe local-file disclosure;
- arbitrary navigation, network, JavaScript, click, or filesystem access;
- credential, browser-profile, attachment, or private-message disclosure;
- non-loopback HTTP exposure; and
- a write reported as verified without its required visible postcondition.

LinkedIn UI changes, ordinary parser drift, account checkpoints, and behavior
already documented as an operator risk are generally bugs rather than security
vulnerabilities unless they cross a trust boundary.

See the detailed [security model](docs/SECURITY.md) for architecture and trust
boundaries.
