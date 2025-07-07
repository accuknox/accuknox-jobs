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

{{- define "kubescape.image" -}}
  {{ include "image-name" (dict "url" .Values.registry.url "owner" .Values.kubescape.owner "repoName" .Values.kubescape.repository "tag" .Values.kubescape.tag "preserve" .Values.registry.preserveUpstream "image" .Values.kubescape.image ) }}
{{- end -}}

{{/* Construct the URL for jobs */}}
{{- define "global.jobURL" -}}
{{- if and .Values.global.enableJobsUrl .Values.global.agents.url -}}
cspm.{{ .Values.global.agents.url -}}
{{- else -}}
{{- default "" .Values.global.enableJobsUrl -}}
{{- end -}}
{{- end -}}