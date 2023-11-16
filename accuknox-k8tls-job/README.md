# AccuKnox k8tls Job

## Helm install

```
helm upgrade --install accuknox-k8tls-job . --set accuknox.authToken="TOKEN"
```
where TOKEN is issued from AccuKnox SaaS.

| Helm key | Default Value |
|----------|---------------|
| accuknox.authToken | "" |
| accuknox.cronTab | "1 0,8,12 * * *" |
