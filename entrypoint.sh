jq '. += {
    "Metadata": {
        "cluster_name":$ENV.CLUSTER_NAME,
        "label_name":$ENV.LABEL_NAME
    }
}' /data/report.json > report_tmp.json && mv report_tmp.json /data/report.json
