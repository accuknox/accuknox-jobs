# 

```bash
docker run --rm -it \
	-e SQ_URL=http://35.188.10.229:9000 \
	-e SQ_AUTH_TOKEN=<AUTH-TOKEN> \
	-e SQ_PROJECTS="^nimbus$" \
	-e REPORT_PATH=/app/data/ \
	-v $PWD:/app/data/ \
	accuknox/sastjob:latest
```

## Configuration

|      Var       | Sample Value              | Description                        |
|----------------|---------------------------|------------------------------------|
| SQ_URL*        | http://35.188.10.229:9000 | SonarQube server URL               |
| SQ_AUTH_TOKEN* | squ_token                 | SonarQube user authn token         |
| SQ_PROJECTS    | "^nimbus$"                | Scan the given projects/components |
| REPORT_PATH    | /app/data/                | Path to keep the report json files |

> variables marked with '*' are mandatory configuration options

## Upload reports to AccuKnox Management Portal

```bash
TENANT_ID=2509
LABEL=SAST
AK_URL="cspm.demo.accuknox.com"
AK_TOK=eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoyNDM5MzY5NDEwLCJqdGkiOiI2MjIzMzFlZjU5N2U0MTM0YjA2ZDliMDMwZGVlNWFjZCIsImlzcyI6ImNzcG0uZGVtby5hY2N1a25veC5jb20ifQ.UTmJak4raCRedTxcS7hQ_Vd2Z96xohzDVgMIoOraUkJErC4JcXn99qlEn8gobDLGaiQv1-IbaAETFGC0UjoTFg3zVIL1A9_uFvEEA-nu-gqf07Dk6krgXVE2qLP3ig8WlUeQCe8TVg50jzDnLck-oAgPHxrjEz0oVs0tK4QbFcHAKmjJWfg-zJjQfxnvZ6e6RfMLPJNmZxhG4Nxox3T57KOGPKE7s38xJb2HdM12JxB1sHPT9HrZ8KekCYhR_MbEZs3XHPMn0ubob5POiNgDkYGwcwV8RTCsZD4KxBoHf1ndBd7nJ_RHHpH8iMXnDo2G9WvJ4s7Iao1xAgiShndVjA

curl --location 'https://$AK_URL/api/v1/artifact/?tenant_id=$TENANT_ID&data_type=SQ&save_to_s3=True&label_id=$LABEL' \
	 --header 'Tenant-Id: $TENANT_ID' \
	 --header 'Authorization: Bearer $AK_TOK' \
	 --form 'file=@"SQ-nimbus.json"'
```
