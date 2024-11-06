#!/bin/sh

# Initialize CURL_FLAGS to handle both insecure and certificate usage
CURL_FLAGS=""

# Always add --insecure if USE_INSECURE_CONNECTION is true
if [ "$USE_INSECURE_CONNECTION" = "true" ]; then
    CURL_FLAGS="$CURL_FLAGS --insecure"
fi

# Add certificate flags if CERT_BUNDLE_PATH is provided
if [ -n "$CERT_BUNDLE_PATH" ]; then
    echo "Using in-line certificate content from CERT_BUNDLE_PATH..."
    printf "%b" "$CERT_BUNDLE_PATH" > /tmp/cert.pem
    CURL_FLAGS="$CURL_FLAGS --cacert /tmp/cert.pem"
elif [ -n "$CERT_BUNDLE_URL" ]; then
    echo "Attempting to download certificate from $CERT_BUNDLE_URL..."
    if curl -o /tmp/cert.pem "$CERT_BUNDLE_URL"; then
        CURL_FLAGS="$CURL_FLAGS --cacert /tmp/cert.pem"
    else
        echo "Certificate not available or failed to download."
    fi
fi

# main curl command
curl --location --request POST "https://${URL}/api/v1/artifact/?tenant_id=${TENANT_ID}&data_type=${DATA_TYPE}&label_id=${LABEL_NAME}&save_to_s3=true" \
    --header "Tenant-Id: ${TENANT_ID}" \
    --header "Authorization: Bearer ${AUTH_TOKEN}" \
    $CURL_FLAGS \
    --form "file=@/data/report.json" || exit 1

# Print the report
cat /data/report.json

