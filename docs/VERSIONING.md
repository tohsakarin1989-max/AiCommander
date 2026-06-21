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

- Version: `1.0.0`
- Tag: `v1.0.0`
- Initial public commit: sanitized single-commit history.
