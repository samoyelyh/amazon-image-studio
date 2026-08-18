# Batch Try-On implementation plan

This document freezes the Phase 2 behavior contracts and the implementation boundaries for the remaining phases. It is not a replacement architecture and does not switch the production workflow.

## Phase 2 frozen contracts

The current `normal_tryon` path must continue to satisfy these contracts while later phases are introduced:

1. The frontend matrix is the Cartesian product of selected templates and selected garments in deterministic template-major order.
2. Every matrix item keeps stable `templateId`, `garmentId`, local image IDs, server Asset IDs, garment source filename, and `client_item_id`. A later garment must never reuse the first garment's image as its variable visual source.
3. Image references are ordered as `[template_asset_id, garment_asset_id]` for every normal try-on Job.
4. One submitted matrix item creates one Job, one quota reservation, one ReviewItem, and one immutable Version v1. These records are joined by stable IDs rather than array positions.
5. `batch_tryon.generate` uses `batch_tryon_queue`; the server batch concurrency is authoritative for dispatch and claim limits.
6. Batch and Job idempotency remain tenant-scoped. Replaying the same request does not create duplicate jobs, reservations, review items, or versions.
7. Successful work settles its reservation, failed or cancelled unconsumed work releases it, and partial completion settles only successful work.
8. Regeneration creates a new Job and Version. Historical Jobs and Versions remain readable, but task-center progress is calculated from each ReviewItem's current Version only.
9. Approval selects the final Version without deleting history. Single download and ZIP export use the server filename contract and unique object-storage keys.
10. Cancelling a queued normal try-on batch cancels its current Jobs, releases their reservations, and synchronizes Version generation status.

The Phase 2 suite protects these contracts through the frontend matrix/queue tests and backend task, quota, review, filename, export, history, cancellation, retry, and submission integration tests.

## Final business rules recorded for later phases

- One batch represents one garment structure family.
- Each template is semantically analyzed at most once per batch.
- The first garment is semantically analyzed at most once per batch.
- Garments 2 through N do not receive AI semantic analysis or per-garment semantic consistency checks.
- The current garment Asset is the only source of variable garment truth for its generation item.
- Front/back semantics and wearer-left/wearer-right semantics are explicit and must not be inferred from array order.
- Prompt construction is deterministic and will ultimately be centralized on the server. AI prompt optimization is not part of the final generation path.
- Quality control remains manual review with targeted per-image regeneration. There is no automatic full-batch visual QC loop.
- The server becomes workflow authority; the frontend becomes submission, status, and review UI.

## Performance targets

These are target-state budgets, not claims about the current production path:

- Pre-generation semantic AI calls per batch: `1 first-garment analysis + T template analyses`, independent of garment count.
- Example target: 100 garments and 10 templates require at most 11 pre-generation semantic AI calls, followed by 1,000 image generation Jobs.
- Prompt assembly per generation item is deterministic and local to the server process; it adds no AI request.
- Batch status is read in aggregate. The UI must not start one polling timer per item.
- Generation throughput is bounded by the minimum of batch concurrency, user/team limits, resource-pool/key capacity, Worker concurrency, and upstream capacity. The UI must display an explicit limiting reason when the requested concurrency is reduced.
- Cancellation and retry are item-targeted and must not resubmit successful matrix items.

## Phase 3 safe frontend extraction boundary — completed

Phase 3 is a mechanical extraction only. It must preserve the existing APIs, payloads, state transitions, Prompt output, and production workflow.

Safe extraction units:

- `useBatchTryOnAssets`: local image selection, server Asset upload/reuse, and template/garment identity mapping.
- `useBatchTryOnMatrix`: selected template/garment state and calls to the existing pure matrix builder.
- `useBatchTryOnSubmission`: construction of the existing `/job-batches` payload and idempotency handling.
- `useBatchTryOnPolling`: one batch-level polling lifecycle, refresh recovery, and cleanup on unmount.
- `useBatchTryOnReviewActions`: approve, regenerate, cancel, and download action state.
- Presentational sections for template management, garment list, generation settings, queue diagnostics, and review dialog.

Unsafe Phase 3 changes:

- Moving Prompt construction to a new implementation.
- Changing reference order, matrix order, IDs, metadata snapshots, or filenames.
- Replacing browser orchestration with a new server workflow.
- Adding `detail_tryon`, automatic QC, or new database tables.
- Removing local recovery state before server read-model parity exists.

Extraction order:

1. Extract read-only selectors and derived view state.
2. Extract Asset identity/upload behavior behind the current callbacks.
3. Extract matrix and payload construction without changing serialized requests.
4. Extract batch polling with fake-timer and unmount cleanup tests.
5. Extract review actions and preserve keyboard/button behavior.
6. Reduce `BatchTryOnWorkspace` to composition only after parity tests pass.

Implemented Phase 3 modules:

- `batchTryOnWorkspaceState.ts`: default/legacy state normalization, size resolution, progress summaries, filename metadata, rerun reset, and server style-profile restoration.
- `batchTryOnServerSync.ts`: current-version Job selection and behavior-compatible Job-to-item state mapping.
- `useBatchTryOnServerPolling.ts`: batch and regeneration polling lifecycle, including 2-second active polling, 5-second retry, refresh recovery, and timer cleanup.
- `batchTryOnSubmission.ts`: stable Asset reference ordering, current garment metadata, existing Prompt Builder invocation, style-profile snapshot serialization, and submitted Job relation mapping.

The workspace was reduced without changing API routes, payload fields, Prompt output, queue behavior, or backend ownership. Upload/link orchestration and interactive review commands remain in the page until Phase 4 provides a server command boundary that can replace them safely.

## Implemented phases 4-9

### Phase 3 — frontend extraction (completed)

Split the workspace along the boundaries above. No API, Prompt, schema, or workflow change.

### Phase 4 — server domain submission (completed)

Introduce the smallest server command/service boundary that accepts stable template and garment Asset IDs and creates the existing batch records. Keep the old endpoint as a compatibility adapter.

Implemented by `POST /batch-tryon/workflows`. The command validates tenant-scoped Project/Asset IDs, explicit combinations, matrix limits, admin concurrency, delivery settings, and idempotency before creating a durable root Job. No new workflow table was required.

### Phase 5 — server workflow authority (completed)

Move pre-generation orchestration to the server and enforce the final AI-call budget. The existing Job, quota, queue, resource-pool, and Worker infrastructure remains in use.

The root Job analyzes only the first garment. It then creates exactly one template-analysis Job per selected template. Idempotent Worker/GET continuation creates the existing image JobBatch after all analyses succeed. Garments 2..N have no semantic analysis or periodic consistency check.

### Phase 6 — server read model (completed)

Provide one authoritative batch read model for progress, limiting reason, style/template snapshots, current versions, review state, and historical links. Retire duplicate browser reconstruction only after parity.

Workflow GET endpoints expose the stable Project, mode, template, garment and combination snapshots plus analysis and batch state. The frontend recovers the latest project workflow after refresh, login change or another computer, then reuses the existing batch read model for Job, diagnostics, ReviewItem and Version state.

### Phase 7 — Prompt consolidation (completed)

Move deterministic Prompt construction into one server Prompt Builder. Freeze front/back and left/right rules with golden tests before switching production.

`batch_tryon_prompt_service.py` now owns normal/detail business prompts and deterministic manual correction constraints. Worker delivery reinforcement is stored separately as `technical_delivery_contract`; the exact upstream `effective_prompt` is persisted on Job metadata and Version snapshots.

### Phase 8 — detail try-on and manual correction (completed)

Add targeted detail editing as a new operation that reuses Asset, Job, Version, quota, and review infrastructure. It must not mutate normal try-on history.

`detail_tryon` is a workflow mode using the same Asset, JobBatch, Job, Worker, Provider, ReviewItem and Version models. Template analysis persists focus/crop/composition constraints. Manual retries accept stable error codes for sleeve side, front/back, text/number, color and detail composition.

### Phase 9 — cleanup (completed)

Remove obsolete browser orchestration and duplicate Prompt paths only after old tasks remain readable and the compatibility endpoint has completed its deprecation window.

Multiuser submission no longer calls the browser style-analysis loop, browser Prompt Builder, model resolver or direct `/job-batches` submission. Standalone local generation and the legacy backend endpoint remain compatibility adapters; historical batches remain readable.

## Compatibility gates for every phase

- Existing `normal_tryon` projects and historical batches remain readable.
- No migration may make existing nullable historical data unreadable.
- Existing download names and object-storage keys remain valid.
- Tenant isolation, permissions, quota idempotency, queue routing, retry, cancellation, review, and version history tests pass.
- Frontend tests and production build pass before advancing to the next phase.
