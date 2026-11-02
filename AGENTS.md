# Fake Farm Data repository instructions

## Shared CI/CD process

- Read [docs/CI_CD.md](docs/CI_CD.md) and `.agrowknow/ci.json` before changing checks, builds or releases. If this checkout predates the rollout, inspect the current GitHub source before adopting it.
- The canonical framework lives in `agrowknow-apps-platform/packages/ci-cd/`. Edit its profile/templates/runtime and use its installer; do not hand-edit generated `scripts/agrowknow-ci/` or locked workflow copies.
- Run the owning product's required checks and relevant platform exports. Keep existing database, authorization, provenance and credential gates. Failed checks block release; never weaken a gate to publish.
- Use reviewed PRs and the required `AgrowKnow CI passed` status on main, retaining existing required checks and independent product releases. Publish the exact tested artifact and verify the candidate and live result.
- Carry forward the chat's authorized commit/push/merge/deployment scope. Otherwise keep work local. Do not enable an additional publisher, native build, store submission, paid resource or data/model pipeline merely because it is configured.
- Record local, GitHub, hosted, native-export and physical-device evidence separately in the existing handoff. Preserve explicit research pauses and owner acceptance gates.
