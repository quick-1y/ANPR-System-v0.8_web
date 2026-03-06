# Web ANPR System

This project is a web-first automatic number plate recognition system.

The system processes multiple video channels on the server side. Each channel works independently and has its own lifecycle, metrics, reconnect behavior, and event flow.

## Architectural Invariants

1. **Web-only product**
   - The browser is the only operator interface.
   - Do not add local GUI runtimes, local orchestration layers, or non-web operator entrypoints.

2. **API-first architecture**
   - Channel lifecycle, channel configuration, ROI, OCR/filter parameters, lists, controllers, telemetry, retention, and exports must be controlled through backend APIs.
   - The web UI is a client of the API, not a second source of truth.

3. **Independent channel processing**
   - Each channel must run independently from other channels.
   - A failure, timeout, reconnect, or restart in one channel must not stop or corrupt other channels.

4. **Server-side ANPR**
   - Detection, OCR, postprocessing, tracking, and event persistence must run on the server.
   - Do not move recognition logic into the browser.

5. **Separate service responsibilities**
   - `apps/api` — backend API, web entrypoint, SSE, channel/config/list/controller/data endpoints
   - `apps/video_gateway` — HLS live preview, profile switching, WebRTC adapter/discovery contract
   - `apps/worker` — retention scheduler and background data lifecycle execution
   - `packages/anpr_core` — channel runtime, event flow, event sinks, service-neutral orchestration
   - `anpr` — reusable domain logic and infrastructure: detection, OCR, pipeline, preprocessing, postprocessing, settings, storage, controllers

6. **Settings are the source of truth**
   - Runtime configuration must be persisted through `settings.json` and managed through `SettingsManager`.
   - Do not introduce parallel configuration sources for channels, storage, ROI, or controllers without a very strong reason.

7. **Storage truth must stay accurate**
   - Documentation and code comments must describe the real current storage behavior.
   - Do not declare a storage model that the implementation does not actually enforce.
   - Storage-related docs must be updated whenever storage behavior changes.

8. **Backward-safe evolution**
   - Prefer additive changes over destructive rewrites.
   - Preserve compatibility of stored settings, event records, exports, and operator workflows whenever possible.

## Current Service Boundaries

### `apps/api`
Owns:
- FastAPI application entrypoint
- Web UI static serving
- Channel CRUD
- Channel lifecycle endpoints: start / stop / restart
- Channel health and telemetry
- SSE stream for live events
- Plate lists and entries
- Controller configuration and test actions
- Data retention policy, manual retention runs, CSV / ZIP export
- Storage mode configuration

Does **not** own:
- FFmpeg HLS process lifecycle
- Media transport orchestration
- Browser-side recognition
- Heavy domain logic that belongs in reusable core modules

### `apps/video_gateway`
Owns:
- HLS preview generation
- FFmpeg process management per active preview session
- Quality profiles (`low`, `medium`, `high`)
- WebRTC integration config / discovery contract for an external provider

Does **not** own:
- ANPR recognition
- Event persistence
- Lists, controllers, or retention policy
- Business configuration storage

### `apps/worker`
Owns:
- Retention scheduler loop
- Periodic cleanup execution
- Worker health endpoint

Does **not** own:
- Channel runtime
- UI behavior
- Video transport
- API orchestration for channel lifecycle

### `packages/anpr_core`
Owns:
- Per-channel runtime orchestration
- Independent channel contexts
- Event sink abstraction
- Event publishing flow

Should remain:
- Service-neutral
- Reusable from API and worker-side orchestration
- Free from UI-specific assumptions

### `anpr`
Owns:
- Detection
- OCR
- Pipeline assembly
- Preprocessing and postprocessing
- Infrastructure adapters such as settings, storage, list DB, logging, controllers

## Runtime Rules

1. **One channel = one isolated runtime context**
   - Keep a dedicated lifecycle and metrics object per channel.
   - Channel state must be observable and restartable independently.

2. **Per-channel faults stay local**
   - Timeouts, reconnects, read failures, OCR errors, and source loss must stay scoped to one channel.
   - Error handling must update channel metrics instead of crashing shared services.

3. **Long-running operations must not block hot paths**
   - Retention, exports, or heavy maintenance tasks must not block frame processing.
   - Operational tasks belong in dedicated paths or services.

4. **Metrics are operational, not decorative**
   - Channel state, fps, latency, reconnect count, timeout count, error count, and last error are part of the operating model.
   - Do not remove or silently repurpose telemetry fields without updating all consumers.

## API and Contract Rules

1. Keep API changes backward-compatible whenever possible.
2. Prefer adding new fields/endpoints over breaking existing ones.
3. Use explicit request/response models and validation for external inputs.
4. Keep operator-facing endpoints stable and predictable.
5. Health endpoints must stay lightweight and side-effect free.
6. Live event delivery is currently based on SSE. Do not silently replace it with another transport without updating architecture docs and consumers.
7. When changing storage behavior, retention behavior, or event payloads, update documentation and migration-related files in the same change.

## Web UI Rules

1. `apps/web` is a thin operator UI, not the place for core business logic.
2. Do not duplicate backend/domain logic in frontend code.
3. Do not access DB/files directly from the UI layer.
4. Keep UI focused on monitoring, control, and operator workflows.
5. Avoid unnecessary frontend complexity. If a framework/build pipeline is introduced, it must have a clear operational benefit and must not complicate deployment without justification.
6. UI state must reflect backend reality, not invent its own lifecycle model.

## Video and Streaming Rules

1. Live preview is an operator feature, not the source of truth for ANPR events.
2. `apps/video_gateway` owns FFmpeg process lifecycle and profile switching.
3. HLS is the current live-preview path.
4. WebRTC support is an adapter/discovery contract for an external provider, not an embedded media server implementation.
5. Do not mix video transport concerns into `apps/api` unless there is a strong architectural reason.

## Storage and Data Lifecycle Rules

1. Event persistence changes must preserve:
   - event timestamps
   - channel identity
   - plate text
   - confidence
   - source
   - country
   - direction
   - media paths when applicable

2. Storage changes must keep retention and export flows consistent.
3. If DB schema or storage flow changes, update all related artifacts together:
   - `README.md`
   - `AGENTS.md`
   - `infra/postgres/schema.sql`
   - migration scripts
   - any storage settings or defaults

4. Do not claim architecture or storage completion unless the code really matches that claim.
5. Prefer non-destructive migrations and explicit transition paths.

## Development Principles

- **SOLID** — clear separation of responsibilities
- **DRY** — do not duplicate channel/runtime/storage logic
- **KISS** — keep implementation simple and operable
- **Modularity** — loosely coupled services and packages
- **Clear ownership** — each module should have one clear reason to change
- **Operational clarity** — code should make runtime behavior easy to understand and debug

## Rules for Changes

When making code changes:

1. Preserve the web-first architecture.
2. Preserve independent channel execution.
3. Keep heavy processing on the server side.
4. Keep service boundaries clear.
5. Avoid shortcuts that mix UI, API, runtime, and transport concerns.
6. Prefer extending reusable modules over scattering similar logic across services.
7. When changing operator-visible behavior, also change the docs in the same task.

## Documentation Rules

1. Update `README.md` in Russian when you add or change:
   - architecture
   - launch flow
   - storage model
   - project structure
   - operator-visible features
   - infrastructure assumptions

2. Update `AGENTS.md` when you change:
   - service boundaries
   - architectural invariants
   - storage truth
   - development workflow rules

3. Keep README product-oriented and clean.
   - README must describe the product and the current architecture.
   - README must not become a migration diary, changelog dump, or backlog note collection.

4. Keep the project structure section in README актуальным.
5. Make all Pull Requests in Russian.

## Forbidden Regressions

Do **not**:
- add local GUI architecture or non-web operator entrypoints
- move ANPR inference into the browser
- tightly couple channels together
- move HLS/FFmpeg gateway logic into the API service without justification
- add undocumented breaking changes to API, storage, or settings
- let frontend become the source of truth for channel state or configuration

## Preferred Direction for Further Evolution

1. Strengthen service separation instead of collapsing services together.
2. Strengthen runtime isolation and observability per channel.
3. Improve storage migration quality without sacrificing correctness or operability.
4. Keep domain logic reusable and independent from delivery mechanisms.
5. Favor explicit, maintainable architecture over quick coupling shortcuts.
