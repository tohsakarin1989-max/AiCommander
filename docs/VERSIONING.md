# Version Management

This repository uses a small, clean branch model:

- `main`: stable public baseline. Keep it releasable.
- `develop`: integration branch for reviewed ongoing work.
- `feature/<short-name>`: feature work branched from `develop`.
- `fix/<short-name>`: bug fixes branched from `develop`, or from `main` for urgent release fixes.
- `vMAJOR.MINOR.PATCH`: release tags on `main`.

Rules:

- Do not commit real secrets, private case data, local databases, office files, or local assistant settings.
- Keep `.env` local; use `.env.example` for placeholders only.
- Before pushing release changes, run frontend tests, typecheck, build, and relevant backend tests.
- Squash or merge reviewed work into `develop`, then fast-forward or merge `develop` into `main` for a release.

Current public baseline:

- Version: `2.0.0`
- Release branch: `codex/v2.0-production`
- The `v2.0.0` tag is created on `main` after review and merge.
- The initial public baseline was created from a sanitized single-commit history;
  the v2.0 release merge reconnects the reviewed development history.

Current test candidate:

- Version: `2.0.1-test`
- Branch: `codex/v2.0-production`
- Purpose: test-server deployment with Agent Lab disabled by default.
- Do not promote to `2.0.2-stable` until backup recovery, core business flows,
  designated-user testing, and the business-efficiency baseline are signed off.
