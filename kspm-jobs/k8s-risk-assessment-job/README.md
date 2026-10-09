# AccuKnox k8s-risk-assessment Job

A job for scanning cluster misconfiguration through kubescape

For upload as each namespace or cluster scan completes, build the updated
scanner and a knoxjobs image with `jobs.reportQueueDir` support, then set:

```yaml
global:
  riskAssessment:
    namespaceDumpIncrementalUpload: true
```

This starts the scanner and uploader as concurrent regular containers, sharing
`/data`. A scope is ready only after both configured frameworks and any fallback
controls complete. The scanner atomically publishes an immutable JSON report and
checksum announcement in `/data/report-uploads`. The uploader uses its existing
KS streaming augmentation, authentication, HTTP/gRPC transport, and retries.
Metadata includes `accuknox_metadata.scan_scope` (`namespace:<name>` or `cluster`).
Successful uploads are checkpointed beside their announcements; uploader
restarts skip acknowledged files. Failed uploads do not prevent attempts to
upload other ready scopes, and the failed uploader restarts to retry pending
files. It exits after the scanner completion manifest and all scope uploads.
After every scope completes, the final deduplicated `/data/report.json` is queued
as a consolidated upload. It is sent only after all namespace and cluster
uploads have successful receipts, and it remains available locally.

After a successful upload, knoxjobs writes its receipt before deleting the queued
JSON payload. Its upload temporary files (augmented JSON, archive, multipart body,
and controls index) are already removed when the upload returns. Failed uploads
retain their payloads for retry.

The scanner durably merges each completed scope into its final SQLite index
before announcing it. Once it observes a matching upload receipt, it removes
that scope's intermediate reports, scan databases, and namespace dump. Findings
and completion checkpoints remain in the final index, so restarts do not rescan
cleaned scopes. Cluster dumps stay until all scopes finish because namespace
scans require them. At the end, the scanner writes the completion manifest and
waits for all scope receipts and the final consolidated upload receipt to finish
cleanup, then removes its active work index. The final `/data/report.json`, diagnostics, and small ready/receipt files
remain. Cleanup primarily frees disk space and reclaimable file cache; it does
not guarantee a decrease in process RSS. In non-incremental mode snapshots and
reports remain available as before.

Upload timeout defaults to 10 minutes per report, including authentication and
transport retries. Set `global.uploadTimeout: "15m"` (or another positive
duration) to write `jobs.uploadTimeout` into each job ConfigMap. Risk-specific
scan settings live under `global.riskAssessment`; only the timeout is shared
between uploaders. When using an umbrella chart, set `global.uploadTimeout`
once at that chart level. Previous top-level scan settings must be moved into
`global.riskAssessment`, and `cluster_job.uploadTimeout` moves to
`global.uploadTimeout`. This applies to HTTP
and gRPC uploads, including queue mode; it does not limit how long the uploader
waits for the scanner. Config is loaded at startup, so deploy a fresh Job or
restart the uploader after changing it. Requires the updated knoxjobs image.

The current values file enables incremental mode. The receiving artifact service must
merge scope uploads for a cluster, rather than replace the entire cluster
snapshot on each request. It must also tolerate repeated uploads: a process
crash after server acceptance but before a local checkpoint can cause a retry.
Already uploaded namespaces remain uploaded if a later scan fails. Reports and
checkpoints survive container restarts in the same pod; a replacement pod starts
fresh. Without this flag the scanner remains an init container and the uploader
sends the final combined report once.

With `global.riskAssessment.scanNamespaceDumps=false`, both the Job and CronJob run one control
in one namespace at a time. The
script `scripts/scan-control-namespaces.py` is copied into the scanner image by
the Dockerfile and invoked as `/usr/local/bin/scan-control-namespaces.py`.
No scan/merge scripts are mounted from a ConfigMap.

Set `global.riskAssessment.scanNamespaceDumps=true` (enabled in the current values file) to
export the configured namespaces sequentially and cluster-scoped resources once.
For each namespace, the scanner runs the complete MITRE framework followed by the
complete NSA framework against that namespace dump plus the cluster-scoped dump.
It then moves to the next namespace. Every scan prints the actual namespace
name and framework. After namespaces, MITRE and NSA also run separately against
the cluster-only dump. Cluster input includes nodes, persistent volumes, CRDs,
storage classes, cluster roles/bindings, namespaces, and admission webhooks. `global.riskAssessment.namespaceDumpFrameworks` controls
framework selection and order; its default is `[mitre, nsa]`.

```yaml
global:
  riskAssessment:
    scanNamespaceDumps: true
    namespaceDumpFrameworks: [mitre, nsa]
    scanNamespaces: [] # Discover all namespaces except openshift-ovn-kubernetes
```

Rebuild and publish the updated Dockerfile and set `kubescape.image` to that image
before deploying. Both the Job and CronJob use this workflow. It honors namespace
selection, airgapped mode, custom controls configuration, and cluster name.
The standalone shell benchmark still scans all dumps together.

Each successful namespace/framework or cluster/framework report is merged into
its own SQLite database and checkpointed
in the same transaction. Init-container restarts in the same pod skip committed
framework scans and reuse saved snapshots and policy artifacts. Progress is logged
and written to `/data/namespace-dumps/run-*/progress.json`. Failed dumps or scans
prevent final publication and upload. One merged v2 JSON report is published to
`/data/report.json` after all scans succeed. Individual framework results are
saved under `/data/namespace-dumps/run-*/reports/namespaces/<namespace>/frameworks/<framework>/report.json`.
The merged namespace report is `reports/namespaces/<namespace>/report.json`;
cluster results are under `reports/cluster`. The final merge deduplicates
resources and resource/control findings, retains distinct rule evidence, and
prefers failures over passes. Changing configuration or upgrading
from an earlier control-batch checkpoint requires a fresh pod.

Before scanning, the job streams each JSON dump to count resources and checks
its byte size. Namespace inputs include both namespace and cluster dumps in these
counts; cluster-only inputs are assessed separately. Inputs over either threshold
run control batches immediately, avoiding a likely failed full-framework attempt.
Smaller inputs try MITRE then NSA as whole frameworks.

| Helm key | Default | Purpose |
|---|---|---|
| `global.riskAssessment.namespaceDumpFullScanMaxResources` | `200` | Largest resource count eligible for a whole-framework attempt |
| `global.riskAssessment.namespaceDumpFullScanMaxBytes` | `2097152` | Largest input size eligible for a whole-framework attempt (2 MiB) |
| `global.riskAssessment.namespaceDumpBatchControls` | `20` | Starting control batch size for larger inputs and queued retries |
| `global.riskAssessment.namespaceDumpBatchMaxControls` | `64` | Maximum adaptive batch size; `0` allows growth to all remaining controls |

These defaults are uncalibrated heuristics, not a guarantee of memory usage.
Both thresholds must be met to try a whole framework; set both to `0` to batch
all nonempty inputs. Decisions and measurements are logged with actual namespace
names and saved to `scan-decisions.json` in the run directory. Dumps contain JSON
(valid YAML) under the existing `.yaml` filenames, allowing streaming inspection
without holding resource objects in memory.

Unexpected memory pressure queues that namespace/framework and switches remaining
frameworks for that namespace directly to batches. The queue is drained after
the first pass. Batch tuning is separate for each framework:

```yaml
global:
  riskAssessment:
    namespaceDumpFrameworkBatches:
      mitre:
        initialControls: 5
        growthStep: 2
      nsa:
        initialControls: 20
        growthStep: 0 # Hold size unless pressure requires a reduction
```

A positive `growthStep` adds that many controls after successful batches below
85% of the effective memory ceiling, with each increase limited to doubling
the previous size. If a proposed size exceeds the ceiling or a successful batch
reaches 90% of it, the batch size halves. After two consecutive low-memory
successes it probes larger batches again; pressure does not create a permanent cap. A framework with `growthStep: 0` holds its confirmed size and halves under pressure.
Other frameworks without overrides keep the generic starting size and doubling
policy. The optional maximum control setting also caps all frameworks.
After pressure, two consecutive low-memory successes are required before growing
again; medium/high memory resets this recovery period.

`framework-batch-tuning.json` in the run directory stores confirmed sizes and
recovery state separately for MITRE and NSA. Old saved pressure bounds are
ignored and removed; only `namespaceDumpBatchMaxControls` imposes a hard cap. Later namespace and cluster scans
reuse confirmed sizes rather than untested growth proposals or short final
batches. Larger or more complex inputs can still force sizes downward. Per-scope
checkpoints take precedence on resume. Tuning survives init-container restarts
in the same pod; a replacement pod or fresh scheduled Job starts learning again.
Successful batch logs show peak memory, the sizing decision, and the next size.
Running scans log elapsed time and memory every 30 seconds. Sizes change between
Kubescape processes; an in-progress batch cannot be resized. Queued whole
framework attempts are not repeated. Non-memory errors still stop the job.
The old initial/max control batch and growth settings are unused.

The current values use a more aggressive throughput trial: MITRE starts at 8
and grows by 8; NSA starts at 32 and grows by 16; batch size is capped at 64.
The Go soft memory limit is 1400 MiB and the watchdog ceiling is 1600 MiB.
Both scanner and uploader containers request 1000 MiB and have a 2 GiB memory limit.
These settings do not guarantee faster scans or memory usage near the ceiling.
Use completed-batch peak memory and elapsed scan time to judge the trial;
`kubectl top` is a sampled current measurement, not the batch peak. If CPU is
saturated or throttled, memory tuning alone may not improve throughput. The
starting values take effect for a fresh pod; learned sizes are reused during a
run. The generic batch setting does not override per-framework starting values.

The memory watchdog stops scans at `global.riskAssessment.namespaceDumpMemoryCeilingMiB` (default
1600 MiB), capped at 80% of a detected cgroup limit. `namespaceDumpGoMemLimit`
(chart default `1400MiB`) and `namespaceDumpGoGC` (chart default `100`) configure the Go runtime.
The watchdog uses current RSS and cgroup working memory, excluding inactive file
cache; historical RSS high-water marks do not trigger it. Watchdog errors include
the current usage, configured/effective ceiling, and detected container limit.
SIGKILL/137 is retried as possible memory pressure but can also be an external kill.
If even one control exceeds the budget, the job fails without publishing the
final report; increase scanner memory and the watchdog ceiling. This workflow does not guarantee a fit within the configured memory limit.

Snapshots and per-framework reports/checkpoints stay under
`/data/namespace-dumps/run-*` until acknowledged incremental uploads are cleaned.
Diagnostics remain; the active work directory is removed after final cleanup. Resource collection uses a fixed subset
of resource types, not every Kubernetes manifest. Namespace separation can affect
cross-namespace checks. The merger retains first-observation summary scores;
these are not recalculated cluster-wide or separate per-namespace compliance scores.
Fallback control scans also do not reconstruct a whole-framework compliance score.

With `global.riskAssessment.scanNamespaceDumps=false`, the original control workflow below applies.

The script streams the unique control IDs from `allcontrols`, `mitre`, and `nsa` definitions into a disk-backed scan plan. It discovers
namespaces using the service account token and Kubernetes API, or uses an
explicit `global.riskAssessment.scanNamespaces` list. `openshift-ovn-kubernetes` is excluded.
For every namespace/control pair it performs these steps in order:

1. Run `kubescape scan control <ID> --include-namespaces <namespace>`.
2. Write the result into a temporary JSON on `/data`.
3. Merge it through SQLite and atomically update `/data/report.json`.
4. Close the merge database, remove the temporary JSON, and collect transient
   Python objects before starting the next scan.

Knoxjobs uploads one final `/data/report.json` after every batch succeeds.
A failed Kubescape control/namespace scan is logged and skipped; remaining
batches continue. No JSON from a nonzero-exit scan is merged. The final report
includes `scanBatchStatus` counts, and `/data/scan-failures.jsonl` lists skipped
pairs. Successful findings can be uploaded even if some controls could not run;
a missing control is not treated as a passed control. If all batches fail, the
init container fails rather than uploading an empty report. Merge/I/O errors
also fail the init container.

Completed/failed batches and merged results are checkpointed in
`/data/.control-ns-scans/merge.sqlite`. Results and successful batch checkpoints
are committed together. An init-container restart in the same pod resumes the
plan, skipping already attempted pairs and rebuilding the snapshot if necessary.
Failed pairs are not retried automatically within that plan. A replacement pod
gets a fresh emptyDir and starts over. A SIGKILL/OOM can leave a temporary JSON;
the next attempt removes it before scanning. The checkpoint database is removed
only after final report generation succeeds. Policy artifacts are not refreshed
when resuming a saved plan.

SQLite's page cache is capped at approximately 1 MiB, memory mapping is disabled,
and SQL temporary data is stored on disk. Merge connections close between scans.
Reports are streamed one record at a time; whole reports are not held in memory.
Runtime buffers and the current resource/summary record still require RAM, and
Kubescape still needs working memory. This is not a guarantee that every batch
fits into 1 GiB. Keep `/data` as disk-backed `emptyDir: {}`, not `medium: Memory`.
Allow space for the growing SQLite index, old/new final report, and one batch.

Resources and resource/control findings are deduplicated, retaining distinct rule
evidence and preferring failed observations over passes. Global scores/counters
and repeated summary entries remain from their first scan; they are not a
recalculated cluster-wide compliance score. Single-control scans also do not
recreate the three original framework compliance scores. Cross-namespace checks
can behave differently when input resources are restricted to one namespace.

Airgapped mode uses image-bundled artifacts copied to `/data/kubescape-cache`.
Online mode refreshes these disk artifacts once before scanning. Custom controls
configuration is downloaded once and applied to every batch. Rebuild and publish
the scanner image and set `kubescape.tag` or `kubescape.image` before deployment.
Use a knoxjobs image supporting streaming Kubescape uploads. Full report logging
is disabled. Artifact definitions remain on disk for the uploader's metadata.

## Helm install

For a standalone memory experiment, dump resources one namespace at a time and
scan the complete dump directory once:

```bash
./scripts/scan-per-namespace.sh /tmp/k8s-dumps
```

This requires `kubectl` with cluster read access, `kubescape`, Bash, and GNU
`time` (override its path with `TIME_BIN`). Additional arguments after the output
directory are passed to `kubescape scan`. Each run uses a fresh directory and
retains dumps, peak RSS measurements in KiB, and `memory-summary.txt`. Exit code
2 indicates skipped dumps, 3 indicates peak RSS at or above 1 GiB, and a failed
Kubescape run returns its own exit code first. Namespace discovery failures stop
the experiment.

Dumping sequentially reduces collection concurrency, but the final scan still
receives all collected resources. This experiment does not guarantee memory
below 1 GiB. GNU time measures process peak RSS; it does not measure total
container memory, including filesystem cache. To verify the existing `1Gi`
container limit, also measure cgroup/container peak memory in the target scanner
environment. This resource list is a subset of the cluster and omits resources
such as nodes, persistent volumes, and CRDs; failed dumps further reduce coverage.
The benchmark does not change the deployed Job or CronJob.

### Local

```
cd k8s-risk-assessment-job
helm upgrade --install k8s-risk-assessment-job . \
-n k8s-risk-assessment --create-namespace \
--set accuknox.authToken="$TOKEN" \
--set accuknox.tenantId="$TENANT_ID" \
--set accuknox.clusterName="$CLUSTER_NAME" \
--set accuknox.URL="cspm.dev.accuknox.com"
```

### Published

```
helm upgrade --install k8s-risk-assessment-job oci://public.ecr.aws/k9v9d5v2/k8s-risk-assessment-job \
-n k8s-risk-assessment --create-namespace \
--set accuknox.authToken="$TOKEN" \
--set accuknox.tenantId="$TENANT_ID" \
--set accuknox.clusterName="$CLUSTER_NAME" \
--set accuknox.URL="cspm.dev.accuknox.com" \
--version="v0.4.0"
```

Where `version` can be taken from the [releases](https://github.com/accuknox/accuknox-jobs/releases) page

### Configuration

| Helm key | Default Value | Description | Required |
|----------|---------------|-------------| -------- |
| accuknox.authToken | "NO-TOKEN-SET" | Auth token from AccuKnox SaaS | YES (auto-populated by SaaS) |
| accuknox.URL | "cspm.demo.accuknox.com" | URL of the environment | YES (auto-populated by SaaS) |
| accuknox.clusterName | "" | name of the cluster | YES (auto-populated by SaaS) |
| accuknox.tenantId | "" | ID of AccuKnox tenant | YES (auto-populated by SaaS) |
| accuknox.clusterID | 0 | ID of the cluster | TBD |
| accuknox.cronTab | "30 9 * * *" | cron tab for the job - timezone: UTC | NO |
| accunkox.label | "" | label of the cluster | NO |
| kubescape.image.repository | "quay.io/kubescape/kubescape-cli" | kubescape image repo | NO |
| kubescape.image.tag | v3.0.8 | kubescape version - taken from appVersion by default | NO |

---

## Manual Procedure

```bash
export URL=cspm.demo.accuknox.com
export TENANT_ID=3730
export LABEL_NAME=STAGEENV
export AUTH_TOKEN=XXXXXXXXXXXXXXXXXXXXX # Get the Token from AccuKnox Management Console
export CLUSTER_NAME=docluster
export CLUSTER_ID=0

curl -s https://raw.githubusercontent.com/accuknox/tools/main/ks/k8srisk.sh | bash
```
