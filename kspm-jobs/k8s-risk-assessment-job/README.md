# AccuKnox k8s-risk-assessment Job

A job for scanning cluster misconfiguration through kubescape

Both the Job and CronJob run one control in one namespace at a time. The single
script `scripts/scan-control-namespaces.py` is copied into the scanner image by
the Dockerfile and invoked as `/usr/local/bin/scan-control-namespaces.py`.
No scan/merge scripts are mounted from a ConfigMap.

The script streams the unique control IDs from `allcontrols`, `mitre`, and `nsa` definitions into a disk-backed scan plan. It discovers
namespaces using the service account token and Kubernetes API, or uses an
explicit `global.scanNamespaces` list. `openshift-ovn-kubernetes` is excluded.
For every namespace/control pair it performs these steps in order:

1. Run `kubescape scan control <ID> --include-namespaces <namespace>`.
2. Write the result into a temporary JSON on `/data`.
3. Merge it through SQLite and atomically update `/data/report.json`.
4. Close the merge database, remove the temporary JSON, and collect transient
   Python objects before starting the next scan.

Knoxjobs uploads one final `/data/report.json` after every batch succeeds.
A failed scan or merge fails the init container, preventing partial upload.
The last successfully merged snapshot remains on disk for diagnosis. Retries
restart the scan plan. The SQLite database is retained between batches to
retain accumulated results and is deleted when the run exits normally or
through a handled exception. SIGKILL/OOM can prevent cleanup; the pod's emptyDir
is removed with the pod.

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
