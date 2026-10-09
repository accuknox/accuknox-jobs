#!/usr/bin/env bash
# Usage: ./scripts/scan-per-namespace.sh [output_dir] [kubescape scan options...]
set -euo pipefail

OUT_DIR="${1:-k8s-dumps}"
if (( $# )); then shift; fi
for command in kubectl kubescape; do
  command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
TIME_BIN="${TIME_BIN:-/usr/bin/time}"
if ! "$TIME_BIN" -f '%M' -o /dev/null true; then
  echo "GNU time is required; set TIME_BIN to its path." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
# A fresh directory prevents a failed dump from leaving stale resources to scan.
RUN_DIR=$(mktemp -d "$OUT_DIR/run-XXXXXX")
mkdir "$RUN_DIR/dumps" "$RUN_DIR/metrics"
echo "Results: $RUN_DIR"

# JSON is valid YAML; retain .yaml filenames for Kubescape input compatibility.
NS_RESOURCES="pods,deploy,sts,ds,job,cronjob,svc,ingress,networkpolicy,sa,role,rolebinding,cm"
CLUSTER_RESOURCES="nodes,persistentvolumes,customresourcedefinitions,storageclasses,clusterrole,clusterrolebinding,ns,validatingwebhookconfiguration,mutatingwebhookconfiguration"
FRAMEWORKS="mitre,nsa"
dump_failures=0
dump_peak_kib=0
measure_dump() {
  local name=$1
  shift
  local status=0 peak
  "$TIME_BIN" -f '%M' -o "$RUN_DIR/metrics/$name.rss-kib" \
    "$@" > "$RUN_DIR/dumps/$name.yaml" || status=$?
  # GNU time may also write an exit-status diagnostic before the final metric.
  peak=$(tail -n 1 "$RUN_DIR/metrics/$name.rss-kib")
  if [[ "$peak" =~ ^[0-9]+$ ]] && (( peak > dump_peak_kib )); then
    dump_peak_kib=$peak
  fi
  if (( status != 0 )); then
    echo "[!] Dump failed: $name (exit $status); skipping" >&2
    rm -f "$RUN_DIR/dumps/$name.yaml"
    dump_failures=$((dump_failures + 1))
  fi
}

# Discovery failure must not silently produce a cluster-only scan.
if [[ -n "${NAMESPACE_FILE:-}" ]]; then
  cp "$NAMESPACE_FILE" "$RUN_DIR/namespaces.txt"
else
  "$TIME_BIN" -f '%M' -o "$RUN_DIR/metrics/namespaces.rss-kib" \
    kubectl get ns -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    > "$RUN_DIR/namespaces.txt"
  dump_peak_kib=$(tail -n 1 "$RUN_DIR/metrics/namespaces.rss-kib")
fi
while IFS= read -r ns; do
  [[ -n "$ns" ]] || continue
  echo "=== Dumping namespace: $ns ==="
  measure_dump "dump-$ns" kubectl get "$NS_RESOURCES" -n "$ns" -o json
done < "$RUN_DIR/namespaces.txt"
echo "=== Dumping cluster-scoped resources ==="
measure_dump dump-cluster-scoped kubectl get "$CLUSTER_RESOURCES" -o json

shopt -s nullglob
if [[ "${DUMP_ONLY:-false}" == true ]]; then
  if (( dump_failures != 0 )); then exit 2; fi
  printf '%s\n' "$RUN_DIR" > "${DUMP_RUN_FILE:?DUMP_RUN_FILE is required in dump-only mode}"
  printf '%s\n' "$dump_peak_kib" > "$RUN_DIR/metrics/dump-peak.rss-kib"
  exit 0
fi
dumps=("$RUN_DIR/dumps/"*.yaml)
if (( ${#dumps[@]} == 0 )); then
  echo "No successful dumps to scan." >&2
  exit 1
fi

echo "=== Running kubescape frameworks $FRAMEWORKS on $RUN_DIR/dumps ==="
scan_status=0
"$TIME_BIN" -f '%M' -o "$RUN_DIR/metrics/kubescape.rss-kib" \
  kubescape scan framework "$FRAMEWORKS" "$RUN_DIR/dumps" "$@" || scan_status=$?
scan_peak_kib=$(tail -n 1 "$RUN_DIR/metrics/kubescape.rss-kib")
if [[ ! "$scan_peak_kib" =~ ^[0-9]+$ ]]; then
  echo "Could not read Kubescape peak RSS." >&2
  exit 1
fi
peak_kib=$scan_peak_kib
if (( dump_peak_kib > peak_kib )); then peak_kib=$dump_peak_kib; fi
{
  echo "dump_peak_rss_kib=$dump_peak_kib"
  echo "kubescape_peak_rss_kib=$scan_peak_kib"
  echo "limit_kib=1048576"
  echo "dump_failures=$dump_failures"
  echo "kubescape_exit_code=$scan_status"
  if (( peak_kib < 1048576 )); then
    echo "memory_result=UNDER_1_GiB"
  else
    echo "memory_result=AT_OR_ABOVE_1_GiB"
  fi
} | tee "$RUN_DIR/memory-summary.txt"
if (( scan_status != 0 )); then exit "$scan_status"; fi
if (( peak_kib >= 1048576 )); then exit 3; fi
if (( dump_failures != 0 )); then exit 2; fi
