# AccuKnox k8s-risk-assessment Job

A job for scanning cluster misconfiguration through kubescape

Both the Job and CronJob scan `allcontrols`, `clusterscan`, `mitre`, and `nsa`
in that order, one process at a time. Each writes `/data/<framework>.json`.
A Python streaming parser and SQLite index on the data volume merge the reports
into `/data/report.json`, which knoxjobs uploads as one artifact. Shared
resources and controls are deduplicated, distinct rule evidence is retained,
and all four framework summaries are preserved. Global summary scores and
counters come from the first (`allcontrols`) scan; they are not recalculated
across overlapping framework results. Conflicting resource snapshots prefer
allcontrols; a failed control observation takes precedence over a pass.

Scan and merge scripts are mounted as individual files under `/data`.
Airgapped artifacts, namespace exclusions, custom controls configuration,
and `--enable-streaming` apply to every scan. A scan or merge failure prevents
uploading an incomplete report. Temporary merge files are removed on completion
or failure, and an existing report is replaced only after a successful merge.

Rebuild and publish the scanner image from this Dockerfile, then update
`kubescape.tag` or `kubescape.image`: Python and `py3-ijson` are now required.
Use a knoxjobs image with streaming Kubescape uploads to avoid loading the
merged report into memory. Allow disk space for all source reports, the SQLite
index and the merged report. Merge memory depends on the largest individual
resource or framework summary, not the sum of all four reports. An individual
scan or upload may still exceed a 2 GiB limit; verify on the affected cluster.
Full uploader report logging is disabled.

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
