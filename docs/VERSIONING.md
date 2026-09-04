# Version Management

This repository uses a small, clean branch model:

- `main`: stable public baseline. Keep it releasable.
- `develop`: integration branch for reviewed ongoing work.
- `feature/<short-name>`: feature work branched from `develop`.
- `fix/<short-name>`: bug fixes branched from `develop`, or from `main` for urgent release fixes.
- `vMAJOR.MINOR.PATCH[-CHANNEL]`: release tags on `main`, where the optional
  channel suffix records a controlled release stage such as `stable`.

Rules:

- Do not commit real secrets, private case data, local databases, office files, or local assistant settings.
- Keep `.env` local; use `.env.example` for placeholders only.
- Before pushing release changes, run frontend tests, typecheck, build, and relevant backend tests.
- Squash or merge reviewed work into `develop`, then fast-forward or merge `develop` into `main` for a release.

Current stable baseline:

- Version: `2.0.3-stable`
- Release branch: `codex/v2.0-production`
- Release tag: `v2.0.3-stable` on `main` after review and merge.
- The initial public baseline was created from a sanitized single-commit history;
  the v2.0 release merge reconnects the reviewed development history.
- Purpose: stable code baseline for controlled test-server deployment, with
  Agent Lab disabled by default.
- Repository automation and isolated production rehearsal are release gates.
  Target-server networking, backup evidence, designated-user testing, and the
  business-efficiency baseline remain deployment acceptance gates and must not
  be represented as completed by the source release alone.
