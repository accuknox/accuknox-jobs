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
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.cluster_job.owner "repoName" .Values.cluster_job.repository "tag" .Values.cluster_job.tag "preserve" .Values.registry.preserveUpstream "image" .Values.cluster_job.image ) }}
{{- end -}}

{{- define "kiem.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.kiem.owner "repoName" .Values.kiem.repository "tag" .Values.kiem.tag "preserve" .Values.registry.preserveUpstream "image" .Values.kiem.image ) }}
{{- end -}}


{{/* Construct the URL for jobs */}}
{{- define "global.jobURL" -}}
{{- if and .Values.global.enableJobsUrl .Values.global.agents.url -}}
cspm.{{ .Values.global.agents.url -}}
{{- else -}}
{{- default "" .Values.global.enableJobsUrl -}}
{{- end -}}
{{- end -}}


{{- define "spire.enabled" -}}
  {{- if .Values.global.agents.joinToken -}}
    true
  {{- else -}}
    false
  {{- end -}}
{{- end -}}


{{/*
Return full spire host like spire.dev.accuknox.com or localhost
*/}}
{{- define "jobs.spireHost" -}}
{{- if .Values.global.agents.joinToken -}}spire.{{ .Values.global.agents.url }}{{- else -}}localhost{{- end -}}
{{- end }}



{{/*
Return KnoxGateway URL with port, like knox-gw.dev.accuknox.com:3000 or empty
*/}}
{{- define "jobs.knoxGatewayHost" -}}
{{- if .Values.global.agents.joinToken -}}knox-gw.{{ .Values.global.agents.url }}:3000{{- else -}}{{""}}{{- end -}}
{{- end }}