# Step 7, part 1: Backend measurement services

Verified on 2026-10-11.

## Implementation

- Pinned `psutil==7.2.2` in the backend dependency lock.
- Added `PinotMetrics`, owned by each shared Pinot client. It retains the latest
  500 individual query timings and returns average/p95/p99 and sample count.
- Timed complete client query execution using `perf_counter`, including failures
  and cancellations. Existing query results, options, and error propagation are
  preserved. Percentiles follow the plan's sorted rounded-index method.
- Added `SystemMetrics`, owned by FastAPI's lifespan. It samples nonblocking CPU
  and RAM once per second on the same event-loop thread, independent of future
  HTTP request frequency. CPU is null until the first sampling interval elapses.
- Cached snapshots include sample timestamps and scope `os_visible_to_backend`.
  Sampling errors preserve the last-good snapshot; shutdown cancels the sampler.
  Memory `_gb` values use binary GiB, following the plan's conversion.

The benchmark API, ingestion freshness/count queries, and dashboard observability
UI belong to subsequent parts and were not added here.

## Validation

| Check | Result |
| --- | --- |
| Backend image build | Passed |
| Complete backend pytest suite | 266 passed (25 added tests) |
| Dependency compatibility (`pip check`) | No broken requirements |
| Real system sampler in temporary container | Passed |
| Timed read-only Pinot query | Passed |
| `git diff --check` | Passed |

New tests cover empty and single-sample summaries, bounded storage, known
percentiles, invalid measurements and intervals, concurrent queries, HTTP errors,
timeouts, malformed responses, cancellation, CPU priming, detached snapshots,
sampling recovery, repeated start/stop, task cleanup, and application lifecycle
cleanup when Kafka startup fails.

The real sampler reported CPU 11.0%, RAM 67.2%, used memory 10.33 GiB and total
memory 15.38 GiB. Values are point-in-time observations, not benchmark results.
The temporary container's psutil total memory was 16,518,270,976 bytes, exactly
matching the host's `/proc/meminfo` total. This validates OS-visible host memory
for this native Linux Docker environment; other environments, especially Docker
Desktop, may expose VM resources instead. These are not cgroup measurements.

The live Pinot read returned 16 v1 rows, with one recorded query sample of
34.63 ms. No generator runs were started and no events were published.
Verification used temporary containers; the running application services were
not restarted, preserving the current run metadata. The new backend image is
built and ready for the next application restart.

The backend suite continues to emit the existing Starlette/httpx deprecation
warning. README documents measurement semantics and access through the internal
service interfaces until the benchmark API is implemented.
