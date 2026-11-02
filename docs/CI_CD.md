
## AgrowKnow CI/CD standard — November 2, 2026

Adopted through reviewed GitHub PRs on November 2, 2026. The root `AGENTS.md`
records the shared working process. Original dirty checkouts remain preserved.
See the shared [operating guide](https://github.com/noahdfreeman/agrowknow-apps-platform/blob/main/docs/operations/CI_CD.md)
for current configuration and future-app onboarding.

`.agrowknow/ci.json` declares this product's checks and release boundary. Versioned
runtime/workflow copies come from platform `packages/ci-cd`; their SHA-256 lock
is checked before CI commands. Update through the platform installer and this
product's normal reviewed PR. Do not hand-edit generated copies.

`AgrowKnow CI passed` is now required on main alongside existing required checks.
PRs must be up to date, conversations resolved, and administrators obey protection.
Preserve these requirements. Later hosting/account changes still require the
owning task's authorized scope.

The existing Python matrix, QGIS package validation and separate tagged release
remain intact. The new common gate waits for the framework contract, unit matrix
and package job. The separately developed, uncommitted Expo frontend is not part
of this tracked plugin release and was not copied, published or started.
