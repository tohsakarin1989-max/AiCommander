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
- Public GitHub updates are normally limited to completed milestones such as `v2.8.0-stable`, `v2.9.0-stable`, and `v3.0.0-stable`.
- Before the single milestone push, complete backend tests, frontend tests, typecheck, build, migration, security, and isolated deployment rehearsal locally.
- Publish one release branch and one pull request, wait for the quality gate, merge to `main`, then create one immutable tag and Release.
- Routine corrections stay local and roll into the next milestone. A production-blocking or security issue may use an exceptional `v2.x.1-hotfix` release.

Current stable baseline:

- Version: `3.0.0-stable`
- Release branch: `codex/v3.0.0-stable`
- Release tag: `v3.0.0-stable` on `main` after review and merge.
- The initial public baseline was created from a sanitized single-commit history;
  the v2.0 release merge reconnects the reviewed development history.
- Purpose: stable code baseline for a read-only dual-domain situation workbench that compares adjacent historical windows, identifies new hotspot and modus changes, ranks well proximity references, and produces no more than three evidence-linked review actions plus a one-page brief. It does not predict crime, dispatch patrols, or require Agent Lab or an external model. The v2.9 evidence graph remains an optional explanation surface rather than an extra workflow step.
- Repository automation and isolated production rehearsal are release gates.
  Target-server networking, backup evidence, designated-user testing, and the
  business-efficiency baseline remain deployment acceptance gates and must not
  be represented as completed by the source release alone.
