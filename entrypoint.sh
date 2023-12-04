cat <<<$(jq '. += { 
    "Metadata": {
        "cluster_name":$ENV.CLUSTER_NAME,
        "label_name":$ENV.LABEL_NAME}}
    ' /data/report.json) >/data/report.json
