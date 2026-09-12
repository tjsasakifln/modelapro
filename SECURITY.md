# Security policy

## Supported release scope

MODELA PRO is currently a release candidate for a single professional on one
local workstation. Shared or Internet-facing operation is not supported. The
shipped configuration binds to loopback and must not be changed to `0.0.0.0`.
Security fixes are provided only for versions explicitly listed as supported in
`docs/comercial/c04/support_and_maintenance.md`.

## Reporting a vulnerability

Do not open a public issue containing client data, credentials, license files,
project archives or an exploit against a live installation. Send a minimal
report to the private security contact designated by the repository owner. The
release owner must publish that contact before commercial release; until then,
the status is `BLOCKED_EXTERNAL_EVIDENCE` and no response-time promise applies.

Include the product version, operating system, affected component, reproduction
steps using synthetic data, impact, and artifact hash. Remove names, addresses,
property data, reports, tokens and keys. Receipt of a report is not permission
to access third-party systems or data.

## Handling process

The maintainer records receipt, severity, affected versions, reachability,
mitigation and disclosure decision. A critical exploitable issue in a shipped
path blocks release until fixed or covered by a documented, approved mitigation.
Dependency alerts are triaged individually; they are neither ignored in bulk nor
treated as automatically exploitable.

No telemetry or project upload is required to diagnose the product. Diagnostic
bundles are local, redacted and reviewed by the operator before sharing.

## Security boundaries

- Loopback is a network exposure reduction, not authentication.
- Software entitlement is not a report signature and validates no calculation.
- Local encryption cannot protect data from a compromised administrator.
- Installer/code signing requires a real key controlled by the release owner.
  Unsigned candidates must be identified as such and are not production-trusted.
