#!/bin/sh
set -eu
if ! command -v python3 >/dev/null 2>&1; then
  echo "Scanner image is missing python3. Rebuild the updated Dockerfile and deploy a new kubescape image tag." >&2
  exit 1
fi
if ! python3 -c 'import ijson, sqlite3'; then
  echo "Scanner image is missing merge dependencies. Rebuild the updated Dockerfile and deploy a new kubescape image tag." >&2
  exit 1
fi
{{- if .Values.global.airgapped }}
mkdir -p /data/kubescape-cache
cp -a /opt/kubescape/artifacts/. /data/kubescape-cache/
{{- end }}
{{- if .Values.global.kraCustomConfig }}
wget -O /tmp/controls.json {{ .Values.global.kraCustomConfig | quote }}
{{- end }}
for framework in allcontrols clusterscan mitre nsa; do
  echo "Scanning framework: $framework"
  set -- scan framework "$framework" --enable-streaming \
    --exclude-namespaces openshift-ovn-kubernetes \
    --format json --format-version v2 \
    --cache-dir /data/kubescape-cache \
    --output "/data/$framework.json" --cluster-name="$CLUSTER_NAME"
{{- if .Values.global.airgapped }}
  set -- "$@" --use-artifacts-from /opt/kubescape/artifacts
{{- end }}
{{- if .Values.global.kraCustomConfig }}
  set -- "$@" --controls-config /tmp/controls.json
{{- end }}
  kubescape "$@"
done
python3 /data/merge-frameworks.py --output /data/report.json \
  /data/allcontrols.json /data/clusterscan.json /data/mitre.json /data/nsa.json
