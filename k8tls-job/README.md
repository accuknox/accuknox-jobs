# AccuKnox k8tls Job

## Helm install

```
helm upgrade --install k8tls-job . --set authToken="TOKEN"
```
where TOKEN is issued from AccuKnox SaaS.

| Helm key  | Default Value |
|---------- |---------------|
| authToken | "NO-TOKEN-SET" |
| cronTab   | "0 0/4 * * *" |
