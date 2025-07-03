# LLM Scan

### Prerequisites:
- [Docker](https://docs.docker.com/engine/install/)
- Parameters as docker environment variables for executing LLM Scan.

### Parameters:
| Parameter              | Description                                                                  | Example / Notes                                       |
| ---------------------- | ---------------------------------------------------------------------------- | ----------------------------------------------------- |
| `endpoint_url`         | The API endpoint of your application.                                        | `https://your-app.com/api/infer`                      |
| `secret_token`         | Secret token to access your application. Leave empty (`"-"`) if not required. | `abc123xyz456` or `"-"`                             |
| `request_template`     | API payload template. Use `$INPUT` as a placeholder for dynamic input.       | `{"prompt": "$INPUT"}`                                |
| `name`                 | Name of the model.                                                           | `my-llm-model`                                        |
| `collector_name`       | Name of the collector.                                                       | `llm-scan-collector`                                  |
| `model_id`             | Unique identifier for the model.                                             | `meta-llama/Llama-3.2-1B`                             |
| `model_type`           | Type of the model. Use `custom` for on-prem or `openai` for OpenAI models.   | `custom`                                              |
| `custom_prompts_file`  | (Optional) Path to a custom prompt JSON file. Leave empty if not used.       | `/path/to/custom_prompts.json` or `""`                |
| `stand_alone` | Boolean flag for on-prem deployments. Set to `True` for on-prem.             | `True`                                                |
| `label`                | Label name defined in Accuknox SaaS.                                         | `llmscan`                                     |
| `CSPM_BASE_URL`        | Accuknox Base URL.                                              | `https://cspm.demo.accuknox.com`                     |
| `internal_tenant_id`   | Tenant ID from your Accuknox SaaS account.                                   | `123`                                                 |
| `ARTIFACT_TOKEN`       | Artifact token from Accuknox SaaS.                                           | `abc123xyz456token`                                   |

## Command for executing LLM Scan:
Running LLM scan & Sending data to AccuKnox SaaS
```bash
docker run --rm \
    -e endpoint_url=$your_model_endpoint \
    -e secret_token=$your_secret_token  \
    -e request_template=your_api_payload \
    -e name=$app_name \
    -e model_id=$your_model_id \
    -e model_type=$model_type \    
    -e collector_name=$name_of_collector \     
    -e stand_alone=True 
    -e internal_tenant_id=$tenant_id \
    -e CSPM_BASE_URL=https://cspm.demo.accuknox.com \ 
    -e label=$label \  
    -e ARTIFACT_TOKEN=$token \        
    accuknox/llm_scan:v1
```
