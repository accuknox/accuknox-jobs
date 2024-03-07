# AccuKnox CIS Job

## Helm install

```
helm upgrade --install accuknox-cis-job . --set accuknox.authToken="TOKEN"
```
where TOKEN is issued from AccuKnox SaaS.

| Helm key | Default Value |
|----------|---------------|
| accuknox.authToken | "NO-TOKEN-SET" |
| accuknox.cronTab | "0 */4 * * *" |
