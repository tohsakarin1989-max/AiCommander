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
- Public GitHub updates are normally limited to completed minor milestones such as `v2.1.0-stable`, `v2.2.0-stable`, and `v2.3.0-stable`.
- Before the single milestone push, complete backend tests, frontend tests, typecheck, build, migration, security, and isolated deployment rehearsal locally.
- Publish one release branch and one pull request, wait for the quality gate, merge to `main`, then create one immutable tag and Release.
- Routine corrections stay local and roll into the next milestone. A production-blocking or security issue may use an exceptional `v2.x.1-hotfix` release.

Current stable baseline:

- Version: `2.2.0-stable`
- Release branch: `codex/v2.2.0-stable`
- Release tag: `v2.2.0-stable` on `main` after review and merge.
- The initial public baseline was created from a sanitized single-commit history;
  the v2.0 release merge reconnects the reviewed development history.
- Purpose: stable code baseline for designated-user Map Data Steward pilot deployment. Agent Lab and external models remain disabled by default; the pilot uses the internal deterministic engine, bounded map asset selection, administrator approval, and a persisted one-click suspension control.
- Repository automation and isolated production rehearsal are release gates.
  Target-server networking, backup evidence, designated-user testing, and the
  business-efficiency baseline remain deployment acceptance gates and must not
  be represented as completed by the source release alone.
