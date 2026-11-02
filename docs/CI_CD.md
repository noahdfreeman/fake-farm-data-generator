
## AgrowKnow CI/CD standard — November 2, 2026

Prepared locally in the isolated `codex/cicd-standard-20261102` worktree. Nothing
staged, committed, pushed, deployed or enabled remotely. Original dirty checkouts
are preserved. See the shared [operating guide](https://github.com/noahdfreeman/agrowknow-apps-platform/blob/main/docs/operations/CI_CD.md) after its coordinated
publication; local source is `../platform/docs/operations/CI_CD.md` relative to
this isolated checkout's root.

`.agrowknow/ci.json` declares this product's checks and release boundary. Versioned
runtime/workflow copies come from platform `packages/ci-cd`; their SHA-256 lock
is checked before CI commands. Update through the platform installer and this
product's normal reviewed PR. Do not hand-edit generated copies.

After the new workflow passes on GitHub, require `AgrowKnow CI passed` on main
alongside existing required checks. Preserve current protection rules. Hosted
secrets/settings and production changes remain separate release scope.

The existing Python matrix, QGIS package validation and separate tagged release
remain intact. The new common gate waits for the framework contract, unit matrix
and package job. The separately developed, uncommitted Expo frontend is not part
of this tracked plugin release and was not copied, published or started.
