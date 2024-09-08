#!/bin/sh

# Handling certificate download
if [ -n "$CERT_BUNDLE_URL" ]; then
    echo "Attempting to download certificate from $CERT_BUNDLE_URL..."
    if curl -o /tmp/cert.pem "$CERT_BUNDLE_URL"; then
        CURL_FLAGS="--cacert /tmp/cert.pem"
    else
        echo "Certificate not available or failed to download."
        CURL_FLAGS=""
    fi
elif [ "$USE_INSECURE_CONNECTION" = "true" ]; then
    CURL_FLAGS="--insecure"
else
    CURL_FLAGS=""
fi

# main curl command
curl --location --request POST "https://${URL}/api/v1/artifact/?tenant_id=${TENANT_ID}&data_type=KB&label_id=${LABEL_NAME}&save_to_s3=true" \
    --header "Tenant-Id: ${TENANT_ID}" \
    --header "Authorization: Bearer ${AUTH_TOKEN}" \
    $CURL_FLAGS \
    --form "file=@/data/report.json"

# Print the report
cat /data/report.json
