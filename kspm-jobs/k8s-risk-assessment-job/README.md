# AccuKnox Kubernetes risk assessment Job

Job and CronJob use two containers:

- Init container `k8s-risk-assessment` downloads manifests and runs Kubescape.
- Container `artifact-api-container` runs knoxjobs once per completed report,
  uploading artifacts with the `AUTH_TOKEN` from the existing secret.

The implementation references `/home/eswar/WORK/knoxjobs`. Set `knoxjobs.image`
to an image built from that repository, including its streaming KS publisher.
`knoxjobs.binaryPath` defaults to `/home/jobs/job`, matching its Dockerfile.
The uploader uses HTTP, with SPIRE disabled, and continues after failed uploads.
A failed upload retains its report; a successful upload deletes its report and
per-report configuration. A partial scan/upload failure makes the job fail after
all available reports have been attempted. Pod restart is disabled to avoid
restarting scans inside the same pod; Kubernetes Job retries can still create
another pod.

## Resource selection and reports

For each namespace, collect only:

- Pods without owner references.
- Deployments, StatefulSets, DaemonSets.
- Jobs not owned by CronJobs, and CronJobs themselves.
- Services, Ingresses, NetworkPolicies, ServiceAccounts.
- Roles, RoleBindings and ConfigMaps.

Secrets, ReplicaSets and controller-owned Pods are excluded. Cluster collection
includes ClusterRoles, ClusterRoleBindings, Namespaces, ValidatingWebhookConfigurations
and MutatingWebhookConfigurations.

The scanner writes `/data/<namespace>.json` for each namespace and
`/data/cluster.resources.json` for the cluster scan. These are Kubescape reports,
not raw manifests. Raw manifests remain in temporary directories under `/data`
and are deleted when scanning finishes. Report names preserve namespace identity;
each is uploaded as a separate artifact.

Each namespace scan includes the cluster snapshot in the same input manifest.
Original names, namespaces, UIDs, labels, ownerReferences, roleRef, subjects and
webhook references are preserved. Namespaced ServiceAccounts referenced by
ClusterRoleBindings and Services referenced by admission webhooks are fetched as
shared reference context, including targets in other namespaces. Duplicate objects
are removed using a disk-backed index before scanning. Missing targets are logged
as dangling references rather than invented. Authorization and API failures abort
collection of the shared context.

Cluster resources can appear in multiple reports because they are scan context.
These snapshots preserve links among the selected objects; they do not provide
host data or resources excluded above, and live API collection is not a single
atomic point-in-time snapshot.

## Configuration

```yaml
namespaceConcurrency: 1
kubescape:
  tag: v0.3.16
  pullPolicy: Always
knoxjobs:
  image: docker.io/seswarrajan/knoxjobs:v0.1.11 # replace with your rebuilt image
  binaryPath: /home/jobs/job
global:
  artifactURL: "https://your-host/api/v1/artifact/?tenant_id=1&data_type=KS&label_id=your-label&save_to_s3=true"
  tenantId: "1"
  clusterName: your-cluster
  clusterID: 0
  label: your-label
  secretName: jobs-token
```

The existing Secret must contain `AUTH_TOKEN`. Set the correct artifact endpoint
or configure the existing SaaS host settings. Custom CA and TLS verification
settings are passed to knoxjobs. The scanner's service account has read access
only to the selected resource types and API discovery.

`namespaceConcurrency` controls simultaneous namespace scans via ConfigMap
`<release-name>-namespace-scan-config`, key `NAMESPACE_CONCURRENCY`. Only positive
integers are accepted. ConfigMap changes apply to new pods. Policy artifacts are
shared as input; writable caches and temporary files are isolated per worker.
Increasing concurrency increases peak memory and disk consumption. One resource
object is parsed at a time, but Kubescape loads the namespace plus cluster context.
Reports for all namespaces accumulate on disk before the uploader starts, so size
`/data` storage accordingly.

Both containers share disk-backed `/data`; ConfigMap content mounts only at
`/data/config`. The scanner script is copied into its image by the Dockerfile.
Online mode downloads policy artifacts including `clusterscan`; airgapped mode
uses image-bundled artifacts. Rebuild the scanner image and point `kubescape.tag`
or `kubescape.image` to it before deploying; rebuild knoxjobs if its published
image does not include the local publisher implementation.

```sh
helm upgrade --install k8s-risk-assessment-job . -n agents -f your-values.yaml
```

Tests cover workload selection, paginated exports, missing TypeMeta, cluster
references, deduplication, report handoff and continuation after scan/upload failures.
SaaS retention and display of separate artifacts require validation in your environment.
