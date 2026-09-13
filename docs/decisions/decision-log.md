# DataFoundry Decision Log

Lightweight ADR-style log for project decisions that are not constitution-level principles.
Constitution (`.specify/memory/constitution.md`) supersedes this log. Entries here record
workflow, scoping, and tooling decisions with rationale.

Format: ID | Date | Status | Decision | Context | Consequences

---

## D-001: Separate git branch per feature

- **Date**: 2026-09-13
- **Status**: Accepted
- **Decision**: Every speckit feature gets its own git branch, named `feature/<NNN>-<short-name>`
  (e.g. `feature/001-one-click-platform-deployment`). Branch created before spec work begins.
  After implementation of that feature completes, changes are committed on the feature branch.
- **Context**: Multiple features (7 planned specs) are developed from one BRD. Working on a
  single branch would mix unrelated feature changes, break reviewability, and violate the
  GitOps principle in the constitution (Git → PR → validation → approval → deployment).
  Spec Kit's `before_specify` git hook is not installed (no `.specify/extensions.yml`),
  so branch creation is done manually as part of the workflow.
- **Consequences**:
  - One branch per feature; no cross-feature commits on the same branch.
  - Commit message convention: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`),
    scoped to the feature, e.g. `feat(001-one-click-platform-deployment): add spec`.
  - Spec artifacts (spec.md, checklists, plan, tasks) and implementation code for a feature
    are committed together on that feature's branch.
  - Merge to main only via pull request after validation, per constitution GitOps gate.

## D-002: Commit after each implementation step

- **Date**: 2026-09-13
- **Status**: Accepted
- **Decision**: Commit changes after implementation of each feature completes, and at
  meaningful checkpoints within a feature (spec written, plan written, tasks written,
  implementation milestones). Never leave uncommitted work spanning multiple features.
- **Context**: User requirement. Supports disaster recovery principle ("everything
  reproducible from versioned sources") and keeps `specs/status.json` consistent with git
  history for debugging.
- **Consequences**: Status file updates are committed alongside the artifacts they describe.
  Git history is granular and traceable per feature step.

## D-003: One specification document per feature (7-feature split)

- **Date**: 2026-09-13
- **Status**: Proposed (awaiting approval)
- **Decision**: Split the BRD into 7 separate speckit feature specs under `specs/`:
  1. `001-one-click-platform-deployment` — one-click deploy, AWS/GCP, Terraform IaC, environments
  2. `002-data-ingestion` — PostgreSQL, SQL Server, CSV, S3/GCS files, wizard config, secure transfer
  3. `003-medallion-processing` — Bronze/Silver/Gold layers, promotion states, transformation
  4. `004-data-quality-gates` — shift-left tests, data contracts, severity, quarantine, override
  5. `005-security-data-protection` — encryption (rest/transit/source-side), column protection, tokenisation, KMS, classification
  6. `006-semantic-layer` — metrics, dimensions, measures, business definitions, access policies
  7. `007-web-ui-control-plane` — UI for platform creation, source config, monitoring, dataset browse, quality, dashboard
- **Context**: User requirement: separate spec document per feature. BRD covers a 3-phase
  product; specs scoped to MVP Phase 1 plus semantic layer and Web UI as explicitly requested.
  AI agents, advanced tokenisation, warehouse/API consumption deferred to later phases.
- **Consequences**: Each feature independently plannable (`/speckit-plan`), taskable, and
  implementable. `.specify/feature.json` points at the currently active feature and must be
  updated when switching between features.

## D-004: JSON workflow status file for debugging

- **Date**: 2026-09-13
- **Status**: Proposed (awaiting approval)
- **Decision**: Maintain `specs/status.json` recording every workflow step: feature id, step
  name, state (pending/in_progress/completed/failed), timestamps, artifacts produced, error
  details, and config snapshot. Updated after every step; committed with the work it describes.
- **Context**: User requirement for an auditable, debuggable record of speckit workflow progress.
- **Consequences**: Single source of truth for "what has run, what is running, what failed".
  Must be kept in sync manually by the agent during workflow execution.
