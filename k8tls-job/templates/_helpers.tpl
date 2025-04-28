{{/*
Expand the name of the chart.
*/}}
{{- define "k8tls-job.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "k8tls-job.fullname" -}}
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
{{- define "k8tls-job.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "k8tls-job.labels" -}}
helm.sh/chart: {{ include "k8tls-job.chart" . }}
{{ include "k8tls-job.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "k8tls-job.selectorLabels" -}}
app.kubernetes.io/name: {{ include "k8tls-job.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "k8tls-job.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "k8tls-job.fullname" .) .Values.serviceAccount.name }}
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

{{- define "k8tls.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.k8tls.owner "repoName" .Values.k8tls.repository "tag" .Values.k8tls.tag "preserve" .Values.registry.preserveUpstream "image" .Values.k8tls.image ) }}
{{- end -}}