{{/*
Expand the name of the chart.
*/}}
{{- define "kiem-job.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "kiem-job.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "kiem-job.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kiem-job.labels" -}}
helm.sh/chart: {{ include "kiem-job.chart" . }}
{{ include "kiem-job.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kiem-job.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kiem-job.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "kiem-job.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "kiem-job.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}


{{- define "image-name" -}}

  {{- $image := .image -}}
  {{- $url := .url -}}
  {{- $owner := .owner -}}
  {{- $repoName := .repoName -}}
  {{- $tag := .tag -}}
  {{- $preserve := .preserve -}}
  {{- $suffix := .suffix -}}

  {{- if $image -}}
    {{- $image -}}
  {{- else -}}

    {{- $parts := list -}}

    {{- if $url -}}
      {{- $parts = append $parts $url -}}
    {{- end -}}

    {{- if $preserve -}}
	    {{- if $owner -}}
	      {{- $parts = append $parts $owner -}}
	    {{- end -}}
	  {{- end -}}

    {{- if $repoName -}}
      {{- if $suffix -}}
        {{- $repoName = printf "%s-%s" $repoName $suffix -}}
      {{- end -}}
      {{- $parts = append $parts $repoName -}}
    {{- end -}}

    {{- $imageName := join "/" $parts -}}

    {{- if $tag -}}
      {{- printf "%s:%s" $imageName $tag -}}
    {{- else -}}
      {{- $imageName -}}
    {{- end -}}

  {{- end -}}

{{- end -}}


{{- define "cluster_job.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.registryName "repoName" .Values.cluster_job.repository "tag" .Values.cluster_job.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.cluster_job.image ) }}
{{- end -}}

{{- define "kiem.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.kiem.owner "repoName" .Values.kiem.repository "tag" .Values.kiem.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.kiem.image ) }}
{{- end -}}


{{- define "global.jobURL" -}}
{{- $root := .Top | default . -}}
{{- $enableJobs := $root.Values.global.enableJobsUrl | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}

{{- if and $enableJobs $root.Values.global.cspmHost -}}
{{ $root.Values.global.cspmHost }}

{{- else if and $enableJobs $url $singleEP -}}
{{ printf "%s" $url }}:{{ $root.Values.global.cspmPort | default 443 }}

{{- else if and $enableJobs $url -}}
cspm.{{ $url }}

{{- else -}}
{{ "" }}

{{- end -}}
{{- end }}



{{- define "spire.enabled" -}}
  {{- if or .Values.global.agents.enabled .Values.global.inClusterScan.enabled -}}
    false
  {{- else -}}
    true
  {{- end -}}
{{- end -}}


{{/*
Return full spire host:
0. If global spireHost set → use it
1. If spire enabled AND SingleEndpointDeployment enabled → <url>
2. If spire enabled → spire.<url>
3. If SingleEndpointDeployment enabled → <url>
4. Else → localhost
*/}}

{{- define "jobs.spireHost" -}}
{{- $root := .Top | default . -}}
{{- $spireHost := $root.Values.global.spireHost | default "" -}}
{{- $spireEnabled := $root.Values.global.agents.enableSpire | default false -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}

{{- if $spireHost -}}
{{ $spireHost }}

{{- else if and $spireEnabled $singleEP -}}
{{ $url }}

{{- else if $spireEnabled -}}
{{ printf "spire.%s" $url }}

{{- else if $singleEP -}}
{{ $url }}

{{- else -}}
localhost

{{- end -}}
{{- end }}




{{/*
Return KnoxGateway URL with port:
1. If spire enabled AND SingleEndpointDeployment enabled → <url>:<port>
2. If ONLY SingleEndpointDeployment enabled → <url>:<port>
3. If spire enabled only → knox-gw.<url>:<port>
4. Else → ""
*/}}
{{- define "jobs.knoxGatewayHost" -}}
{{- $root := .Top | default . -}}
{{- $spireEnabled := eq (include "spire.enabled" $root) "true" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}
{{- $port := int ($root.Values.global.OnePort | default ($root.Values.global.knoxGatewayPort | default 3000)) -}}

{{- if and $spireEnabled $singleEP -}}
{{ printf "%s:%d" $url $port }}

{{- else if and (not $spireEnabled) $singleEP -}}
{{ printf "%s:%d" $url $port }}

{{- else -}}
{{ printf "knox-gw.%s:%d" $url $port }}

{{- end }}
{{- end }}




{{/*
Return access key URL:
1. If accessKey exists AND SingleEndpointDeployment enabled → <url>/access-token/api/v1/process
2. If accessKey exists only → https://cwpp.<url>/access-token/api/v1/process
3. Else → ""
*/}}
{{- define "jobs.accessKeyUrl" -}}
{{- $root := .Top | default . -}}
{{- $accessKey := $root.Values.global.agents.accessKey | default "" -}}
{{- $singleEP := $root.Values.global.SingleEndpointDeployment | default false -}}
{{- $url := $root.Values.global.agents.url | default "" -}}

{{- if and $accessKey $singleEP -}}
{{ printf "%s/access-token/api/v1/process" $url }}

{{- else if $accessKey -}}
{{ printf "https://cwpp.%s/access-token/api/v1/process" $url }}

{{- else -}}
{{ "" }}
{{- end }}
{{- end }}


{{/*
Return cluster name for jobs pod
*/}}
{{- define "jobs.clusterName" -}}
{{- coalesce .Values.global.clusterName .Values.global.agents.clusterName -}}
{{- end -}}


{{- define "spire.agent" -}}
  {{- if eq .Values.global.agents.enabled true -}}
    {{- printf "agents-operator.%s.svc.cluster.local:9091" .Release.Namespace -}}
  {{- else if eq .Values.global.inClusterScan.enabled true -}}
    {{- printf "kubeshield-spire-agent.%s.svc.cluster.local:9091" .Release.Namespace -}}
  {{- else -}}
    "localhost:9091"
  {{- end -}}
{{- end -}}
