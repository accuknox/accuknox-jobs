{{/*
Expand the name of the chart.
*/}}
{{- define "kspm-runtime.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a fullname combining release name and chart name.
*/}}
{{- define "kspm-runtime.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := include "kspm-runtime.name" . }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Return the chart version.
*/}}
{{- define "kspm-runtime.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{/*
Helper to check if Spire is enabled.
*/}}
{{- define "spire.enabled" -}}
{{- if .Values.spire.enabled }}
true
{{- else }}
false
{{- end -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "kspm-runtime.labels" -}}
helm.sh/chart: {{ include "kspm-runtime.chart" . }}
app.kubernetes.io/name: {{ include "kspm-runtime.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
