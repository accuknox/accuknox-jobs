# 🔍 Checkmarx ONE API Docker Job

This Docker job fetches **scan results** from [Checkmarx](https://www.checkmarx.com/) in JSON format and uploads them to the [AccuKnox](https://accuknox.com) SaaS portal.

## 🚀 Usage

### 1️⃣ Create a `.env` file
Add the required environment variables from **Configuration**  to a `.env` file in your working directory:

### 🐳 Docker Run Example

```bash
rm -f Checkmarx-*.json # Remove existing reports (optional cleanup)

docker run --rm -it \
  --env-file .env \
  -v $PWD:/app/data/ \
  accuknox/checkmarx-one-job:1.3
```

> This will generate `Checkmarx-*.json` files in the current directory, one per project/component found.

---

## ⚙️ Configuration

| Environment Variable | Sample Value                             | Description                                          |
|----------------------|------------------------------------------|------------------------------------------------------|
| `API_KEY`*           | `eIGNiD384Tg`                            | API key token to authenticate with Checkmarx API     |
| `PROJECT_NAMES`*     | `Accuknox/checkmarx:main`                | Comma-separated project names in format project:branch (e.g., org1/proj1,org2/proj2). If a branch is not specified for a project, the latest scan across all branches will be used.                  |
| `CSPM_BASE_URL`\*    | `https://cspm.demo.accuknox.com`         | AccuKnox CSPM API Endpoint                               |
| `LABEL`\*            | `$LABEL `                                | The label created in AccuKnox SaaS for associating scan results |
| `TENANT_ID`\*        | `$TENANT_ID$`                            |  The ID of the tenant associated with the CSPM panel   |
| `ARTIFACT_TOKEN`\*   | `$ARTIFACT_TOKEN`                        | The token for authenticating with the CSPM panel |

> **Note:** Variables marked with `*` are mandatory.

---
