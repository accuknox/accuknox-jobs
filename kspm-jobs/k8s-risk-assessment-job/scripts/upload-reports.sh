#!/bin/sh
# Run knoxjobs once per completed report; do not stop on an upload failure.
set -u
data_dir=${SCAN_DATA_DIR:-/data}
failed=0
count=0
for config in "$data_dir"/upload-configs/*.json; do
    [ -f "$config" ] || continue
    name=${config##*/}
    echo "Uploading artifact: $name"
    if "$KNOXJOBS_BINARY" -config "$config"; then
        count=$((count + 1))
        rm -f "$data_dir/$name" "$config"
    else
        failed=$((failed + 1))
        echo "Upload failed for $name; retaining report and continuing"
    fi
done
if [ -f "$data_dir/scan-failures.txt" ]; then
    cat "$data_dir/scan-failures.txt"
    failed=$((failed + 1))
fi
if [ "$count" -eq 0 ]; then
    echo "No artifacts uploaded"
    failed=$((failed + 1))
fi
echo "Artifact processing finished: $count uploaded, $failed failures"
[ "$failed" -eq 0 ]
