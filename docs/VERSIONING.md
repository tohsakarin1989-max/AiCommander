# Version Management

This repository uses milestone releases to keep GitHub work concentrated:

- `main`: stable public baseline. Keep it releasable.
- Local `codex/vMAJOR.MINOR.PATCH-stable` branches: incremental development and local verification. Do not push each internal checkpoint.
- Internal labels such as `dev`, `shadow`, `demo`, and `rc`: local progress only; no GitHub tag or Release.
- `vMAJOR.MINOR.PATCH[-CHANNEL]`: release tags on `main`, where the optional
  channel suffix records a controlled release stage such as `stable`.

Rules:

- Do not commit real secrets, private case data, local databases, office files, or local assistant settings.
- Keep `.env` local; use `.env.example` for placeholders only.
- Public GitHub updates are normally limited to completed minor milestones such as `v2.6.0-stable`, `v2.8.0-stable`, and `v2.9.0-stable`.
- Before the single milestone push, complete backend tests, frontend tests, typecheck, build, migration, security, and isolated deployment rehearsal locally.
- Publish one release branch and one pull request, wait for the quality gate, merge to `main`, then create one immutable tag and Release.
- Routine corrections stay local and roll into the next milestone. A production-blocking or security issue may use an exceptional `v2.x.1-hotfix` release.

Current stable baseline:

- Version: `2.8.0-stable`
- Release branch: `codex/v2.8.0-stable`
- Release tag: `v2.8.0-stable` on `main` after review and merge.
- The initial public baseline was created from a sanitized single-commit history;
  the v2.0 release merge reconnects the reviewed development history.
- Purpose: stable code baseline for a role-aware daily analysis workbench, one-next-action case routing, resumable work sessions, and privacy-minimized utility metrics while retaining versioned knowledge assets, the unified Agent operations center, both data stewards, and read-only dual-domain analysis. Workbench routing never modifies formal case data; Agent Lab and external models remain disabled by default.
- Repository automation and isolated production rehearsal are release gates.
  Target-server networking, backup evidence, designated-user testing, and the
  business-efficiency baseline remain deployment acceptance gates and must not
  be represented as completed by the source release alone.
