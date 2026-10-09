# AccuKnox k8s-risk-assessment Job

A job for scanning cluster misconfiguration through kubescape

Both Job and CronJob use one `k8s-risk-assessment` container. Its image-bundled
`scripts/scan-and-upload.py` processes all namespaces with configurable concurrency:

1. Discover every listable namespaced Kubernetes resource type, including Secrets,
   Roles, RoleBindings, workloads and custom resources. Download one namespace
   into a multi-document manifest on disk, with API pagination and streaming JSON.
2. Run `kubescape scan framework allcontrols,clusterscan,nsa,mitre <manifest.yaml>`
   against that file, producing `report.json` for that namespace.
3. Add generation time, deduplicated control definitions and `accuknox_metadata`
   containing the cluster identity, label and namespace.
4. Upload the completed report once to the SaaS artifact API as a multipart
   `file` containing `report.json.tar.gz`, using `Authorization: Bearer AUTH_TOKEN`
   and `Tenant-Id`. HTTP 200 confirms acceptance; failed uploads retry three times.
5. Delete the namespace manifest, report, SQLite metadata database, archive and
   multipart body before moving to the next namespace, including after failures.

Failures during collection, scanning or upload are logged, and remaining
namespaces are attempted. Incomplete snapshots are never uploaded. The job exits
unsuccessfully after processing all namespaces if any failed. A pod restart starts
again; this loop does not persist progress checkpoints.

The service account has read access to all resources and API discovery so new
namespaced CRDs are included. Cluster-scoped resources (such as ClusterRoles,
ClusterRoleBindings and Nodes) are outside namespace snapshots. Consequently,
controls requiring cluster or host context cannot be fully assessed from these
manifests. Every namespace is included, including `openshift-ovn-kubernetes`.

No knoxjobs container is needed. Supply an `AUTH_TOKEN` key in
`global.secretName` (default `jobs-token`), read from `authTokenPath`. Set
`global.tenantId`, `global.label`, `global.clusterName` and `global.clusterID`.
The token's `tenant-id` claim overrides the configured tenant header as in knoxjobs.
Set `global.artifactURL` to the full endpoint including required query parameters,
or configure the existing SaaS host settings. Custom CA certificates and
`global.skipTLSVerification` remain supported for the artifact API; Kubernetes
API connections always use the service-account CA and token.

Temporary files stay in private directories on the disk-backed `/data` volume.
Reports and request bodies are streamed rather than loaded entirely into Python
memory. Kubescape still needs RAM for one namespace's manifest; a large namespace
can exceed the configured limit. Policy artifacts are cached on disk across
namespaces. Secrets are included in snapshots and may appear in uploaded results;
manifest contents and complete reports are not printed by this script.

Online mode downloads policy artifacts and the requested `clusterscan` definition.
Airgapped mode uses image-bundled artifacts. Rebuild and publish the scanner image,
then update `kubescape.tag` or `kubescape.image` before deploying. Artifact API
acceptance is verified locally by tests; SaaS retention and display of separate
namespace artifacts require validation in your environment.

## Helm install

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

## Namespace concurrency

Set `namespaceConcurrency: 3` in Helm values to process up to three namespaces
at once. The chart writes this setting to ConfigMap
`<release-name>-namespace-scan-config`, key `NAMESPACE_CONCURRENCY`; both Job and
CronJob read it through their environment. The default is `1`. Only positive
integers are accepted. ConfigMap changes apply to newly created pods; recreate
the Job to use a new setting immediately. Helm upgrades restore the Helm value.

Each worker independently downloads, scans, uploads and deletes its namespace
files. Workers use separate temporary directories and writable Kubescape caches;
downloaded policy artifacts are shared as input. Only `n` namespace tasks are
queued at a time. Higher concurrency runs multiple Kubescape processes and
increases peak RAM and disk use; size container limits accordingly.
