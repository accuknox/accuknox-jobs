# Kubernetes resource scanning job

In large-cluster mode, the Job and CronJob download selected resources, run
Kubescape on temporary local manifests, and retain scan reports. Knoxjobs uploads
the completed reports and the final consolidated report using the configured
SaaS credentials.
Set `global.riskAssessment.largeCluster=true` to run `scan-resources.py` as a
regular container using `kubescape.newTag` in both the Job and CronJob. When false,
the scanner remains an init container using `kubescape.tag` and the legacy script.
Rebuild both the scanner and knoxjobs images, then set `kubescape.newTag` and
`cluster_job.tag` before deploying large-cluster mode.
An explicit `kubescape.image` overrides tag selection in either mode.
The image entry point is `scripts/scan-resources.py`. Each namespace scan receives
one combined manifest containing all retained namespaced resource types so
Kubescape can evaluate relationships between them.

Namespaced types: pods, deployments, statefulsets, daemonsets, jobs, cronjobs,
services, ingresses, networkpolicies, serviceaccounts, roles, rolebindings, configmaps.
Owned Deployments, StatefulSets, DaemonSets, CronJobs, and Jobs not owned by a
CronJob are retained: their specs are not covered by scanning the owning operator.
Controller-created Pods and CronJob-created Jobs are omitted. Other owned
namespaced types remain filtered; absent, null, or empty owner references are
retained. ReplicaSets, Secrets, CRDs and other unlisted types are not requested.

Cluster types, collected once: clusterroles, clusterrolebindings,
validatingwebhookconfigurations, mutatingwebhookconfigurations.

Configure type selection with comma-separated strings:

```yaml
global:
  riskAssessment:
    collectAllResources: false
    namespaceResources: "pods,deploy,sts,ds,svc,cm"
    clusterResources: "clusterroles,clusterrolebindings"
```

Empty strings use the baseline lists above. The settings accept plural resource
names, kinds, and baseline aliases. Types outside the baseline are resolved using
API discovery; custom types may use `widgets.example.io` to distinguish API groups.
Unknown, non-listable, wrong-scope or ambiguous types fail with an error rather than
silently reducing coverage. Secrets remain excluded. Duplicate entries are ignored.
For direct execution, use `NAMESPACE_RESOURCES` and `CLUSTER_RESOURCES`.
With Helm CLI, escape commas, for example
`--set-string 'global.riskAssessment.namespaceResources=pods\,deploy\,ds'`.

`collectAllResources=true` overrides both selections and scans all discovered
listable types except Secrets. In selected mode, the cluster selection limits both
standalone cluster scans and the types available for namespace context. Custom
selections enable wildcard `get`/`list` RBAC to support arbitrary API resource types;
the collector still downloads only selected types.

Cluster objects are scanned regardless of owner references. Each cluster type
has its own manifest and Kubescape process. By default, cluster manifests are not added to namespace scans.
Set `global.riskAssessment.includeClusterContext: true` (or `--set global.riskAssessment.includeClusterContext=true`) to include
only relevant cluster objects in each nonempty combined namespace scan:

- ClusterRoles referenced by RoleBindings, including aggregation dependencies.
- ClusterRoleBindings for service accounts used by retained workloads or present
  in the namespace, including standard service-account groups, and
  the ClusterRoles they reference.
- Webhook configurations whose rules and namespace/object selectors match the
  scanned resources (including workload Pod templates), or whose backend Service
  is the scanned Service.
- In all-resource mode, explicit storage/scheduling references, cluster owner
  references, the namespace object, CRD definitions used by namespace custom
  resources, and typed custom references (`kind`/`name`), with transitive cluster
  dependencies.

No related object means no cluster context is added to that scan. Unknown user or
custom-group membership cannot be inferred from manifests. Webhook CEL
`matchConditions` and equivalent API versions are treated conservatively: a
configuration matching the basic rules/selectors is retained. Relationship
selection is based on the entire retained namespace input, not runtime access history. Standalone cluster scans still run separately by type.
Cluster resources are downloaded once and retained as separate temporary files,
shared read-only across namespace workers, then removed when the run finishes.
Namespace reports can also contain cluster-resource findings in this mode.
This adds memory and policy evaluation work to each namespace scan, especially
with concurrency. Only the configured resource types and retained objects are
included; controls requiring omitted types, live child Pods, host data, or other
namespaces can still lack context.

Output files contain Kubescape JSON v2 scan results:

- `/data/<namespace>/report.json`
- `/data/clusterscoped/<resource>.json`

Cluster report filenames use canonical plural API names, for example
`clusterroles.json`. Namespace reports now use `report.json` instead of separate
resource-type reports. Consolidation reads matching reports from the completed-report directory.
Each report runs the `allcontrols`, `clusterscan`, `nsa`, and `mitre` frameworks.
All scans pass `--keep-local --use-default` to prevent backend reporting and use
local policy definitions alongside `--use-artifacts-from`. The shared service account for Job and CronJob has read access to the collected
resource types, API discovery, and both `securityexceptions` and
`clustersecurityexceptions` in `kubescape.io`. It can also create/patch Kubernetes
Events for exception-match auditing. Apply the updated chart to fix the reported
security-exception permission errors; an image rebuild alone does not update RBAC.
Empty namespaces and empty standalone cluster types are skipped, with any stale
report at their output path removed.
Temporary manifests, policy artifacts, and partial reports are removed after use.
Reports replace previous files only after scanning and JSON validation succeed.
After every scan succeeds, the container merges all completed `*-report.json` files into
`/data/report.json`, writes `scan-done`, and exits immediately. Individual scan
reports remain available. Failed runs do not consolidate.
The SQLite-backed merge deduplicates resources and controls, retains distinct rule
evidence, and preserves failed observations when duplicate controls disagree.
Summary scores and counters come from the first report; they are not recalculated
as cluster-wide totals. Existing files from previous runs are not merge inputs.
An empty run produces a valid empty report. No results are uploaded to SaaS.
All namespaces are attempted after a namespace fails; failures fail the job.

Online mode downloads policy artifacts once per run. `global.airgapped: true`
uses image-bundled artifacts. `global.kraCustomConfig` optionally supplies a
controls configuration URL.

Cluster context is collected before namespace work starts when enabled.
Standalone cluster resource types are scanned sequentially after namespace work,
including objects unrelated to any namespace.
Set `global.riskAssessment.namespaceConcurrency: 2` (current default `5`) to scan two namespaces concurrently.
Each worker collects all retained namespace types and scans them together, using
a separate API client, scratch
directory, and writable Kubescape cache. Policy artifacts are shared read-only.
Only the configured number of namespace tasks are queued at once.
Increasing concurrency increases total pod memory use; configure
`global.job.resources` accordingly. Job and CronJob read concurrency from
`<release-name>-namespace-scan-config`.
Set `global.riskAssessment.kubernetesPageSize: 100` (or `--set global.riskAssessment.kubernetesPageSize=50`) to choose the
positive number of items requested per list page. All namespace, namespaced,
and cluster resource lists use `limit` and follow `metadata.continue` until empty.
The API server can return fewer items than requested. Collection uses disk-backed
streaming, never loading a complete API response or resource list. Context
selection projects namespace metadata/references and stores selected identities
in SQLite; cluster objects are read one at a time. Kubernetes still sends
owned objects; they are filtered before scanning. Kubescape memory use depends
on the size of the combined namespace input and selected cluster context. The previous collector-only synthetic
memory measurement does not measure Kubescape. No live-cluster memory benchmark
was run.

The default container limit is `1Gi`. Configure requests and limits through
`global.job.resources`; the chart passes values through without validation or a
cap, including `1G`, `1.5G`, or `2Gi` memory limits.

The output directory defaults to `/data`. Set `--set global.riskAssessment.outputPath=/reports/scans`
to change both the container's data volume mount and scanner output directory.
When running the script directly, set `OUTPUT_PATH=/reports/scans`. Missing
directories are created before writing. Reports are saved as
`<outputPath>/<namespace>/report.json`, `<outputPath>/clusterscoped/<resource>.json`
and `<outputPath>/report.json`.

Set `global.riskAssessment.completedReportsPath` to choose the directory for
completed scan reports (ConfigMap key `COMPLETED_REPORTS_PATH`). Empty defaults to
`<outputPath>/completed`. Missing directories are created. Each namespace report
is copied atomically as `<namespace>-report.json` as soon as it finishes; each
cluster type is published as `<resource>-report.json` immediately after its scan.
Custom cluster types retain the API-group suffix in their resource filename.
Original per-scan reports are retained too.

After all scans succeed, consolidation reads **all** `*-report.json` files in this
directory and writes `<outputPath>/report.json`. Previously saved matching files
are included; use a fresh directory for each run if reusing persistent storage and
you want only the current run's results. Other filenames and temporary partial
copies are ignored. An external completed-report path gets its own disk-backed
`emptyDir` mount in both the Job and CronJob.

The output directory is a disk-backed `emptyDir`, retained for the pod lifetime. Copy files out
before the pod is deleted (successful Jobs expire after two hours), or replace the
volume with persistent storage if longer retention is needed.

```sh
helm upgrade --install k8s-risk-assessment-job . \
  -n k8s-risk-assessment --create-namespace \
  --set kubescape.image=<rebuilt-image>
```

Run local checks with `python3 -m unittest discover -s tests` and `helm lint .`.

Progress is printed to container logs. Follow it with:

```sh
kubectl logs -n <namespace> <pod> -c k8s-risk-assessment -f
```

`Progress [namespaces]` shows completed, failed, active, pending (not yet queued),
and the percentage finished. Each namespace logs resource-type collection
progress and then the start/completion of its combined scan. `clusterscoped` logs
resource types completed, scanned, skipped, and pending. Empty cluster types
count as completed but skipped. Namespace totals are counted on disk before workers start; failed
namespaces count as finished, not successful. A failed namespace may leave later
resource types unattempted. Progress is task-count based, not elapsed-time or
within-scan completion. Consolidation is logged separately.
After merging `/data/report.json`, a `Timing:` log reports preparation, collection
and scan time, merge time, and total elapsed wall time. Concurrent namespace scans
share the same elapsed timer.

Each list logs `fetched`, `excluded_owned`, and `retained` counts. Filtered generated Jobs and retained owned parent workloads are named in logs.
An operator-owned DaemonSet is retained because the operator Deployment does not
contain that DaemonSet's workload spec.

Each report includes `collectionAudit`: input counts by kind, counts represented
in output (including related objects), and up to 20 examples of inputs absent
from report output. All per-scan audits are preserved in `results.json` under
`collectionAudits`. This measures input/output representation, not policy
coverage: resources with no applicable controls may not appear in results.
A missing DaemonSet in input points to filtering/collection; a DaemonSet in input
but absent from output points to Kubescape output or evaluation behavior.

Configure scanner settings from either this chart or the parent chart with:

```sh
--set global.riskAssessment.namespaceConcurrency=5 \
--set global.riskAssessment.kubernetesPageSize=250 \
--set global.riskAssessment.includeClusterContext=true
```

In a values file, use the nested structure:

```yaml
global:
  riskAssessment:
    namespaceConcurrency: 5
    kubernetesPageSize: 250
    includeClusterContext: true
```

The former top-level scanner settings have moved to `global.riskAssessment`.
Current values (concurrency `5`, context `true`, page size `100`) are preserved.

The scanner handles SIGTERM and SIGINT. It immediately stops normal execution,
sends SIGTERM to active Kubescape process groups (including downloads), allows
up to two seconds for them to exit, then sends SIGKILL to remaining groups and
exits. It also exits promptly during API waits or consolidation without waiting
for namespace worker threads. Reports already published
remain intact; shutdown can leave private temporary files until the pod is deleted.
SIGKILL cannot be caught and stops the container immediately. Allow at least a
few seconds of pod termination grace time for SIGTERM handling.

Enable discovery-based collection from either the standalone or parent chart:

```sh
--set global.riskAssessment.collectAllResources=true \
--set global.riskAssessment.includeClusterContext=true \
--set global.riskAssessment.namespaceConcurrency=5 \
--set global.riskAssessment.kubernetesPageSize=250
```

`collectAllResources` defaults to `false`, preserving the selected-resource
baseline. When enabled, the scanner discovers all listable namespaced and
cluster-scoped API resource types, including custom resources, excluding core
Kubernetes Secrets. It
uses one preferred served version per API group and skips subresources and types
without `list` support. The owner filtering policy remains in effect; this flag
expands resource types, not generated workload copies. Kubescape may have no
applicable controls for some custom types.

Discovery mode adds wildcard `get`/`list` resource grants to the shared service
account, so upgrade the Helm chart as well as rebuilding the image. Secret
manifests are not requested or added to scan inputs.
All lists remain paginated and streamed to disk; a namespace is scanned as one
combined input with relevant cluster context when enabled. Cluster snapshots
are reused for standalone type-by-type scans after all namespace work finishes.
Non-baseline cluster report filenames include their API group to avoid collisions
(e.g. `nodes.core.json`, `policies.example.io.json`). API collection failures fail
the run rather than claiming full collection.

Context matching supports known references and explicit typed custom references;
it cannot infer every arbitrary CRD's semantic relationships, implicit storage
provisioning defaults, or scheduling choices absent from retained manifests.
Unknown cluster objects are still assessed by standalone scans. Memory use can
increase substantially with broader inputs; no live-cluster memory measurement
or new deployment was performed for this mode. Existing resource limits,
progress logs, audits, consolidation, and SIGTERM handling apply.


With `global.riskAssessment.largeCluster=true`, knoxjobs watches the completed
report directory and uploads each `*-report.json` serially through its existing
SaaS logic. The scanner keeps control artifacts under `<outputPath>/kubescape-cache`
for upload metadata and atomically writes a `scan-done` marker after consolidation.
Knoxjobs attempts every remaining individual report before uploading
`<outputPath>/report.json` last. Individual failures are logged and skipped;
the final upload determines whether knoxjobs exits successfully. Scanner failure
writes `scan-failed`, which allows pending individual reports to be attempted
before knoxjobs exits with an error. Upload records in `.uploaded` prevent
repeating individual attempts across polling cycles and container restarts.

Each report upload defaults to a ten-minute deadline. Configure
`global.jobs.flushTimeout: "10m"` for all jobs, or set
`global.riskAssessment.flushTimeout: "5m"` to override it for this job.
An empty job-specific value inherits the shared setting. This applies to both
regular and large-cluster modes.
