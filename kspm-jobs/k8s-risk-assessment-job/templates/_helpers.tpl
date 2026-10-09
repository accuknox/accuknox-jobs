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


{{- define "kubescape.image" -}}
  {{ include "image-name" (dict "url" .Values.global.registry.url "owner" .Values.registryName "repoName" .Values.kubescape.repository "tag" .Values.kubescape.tag "preserve" .Values.global.registry.preserveUpstream "image" .Values.kubescape.image ) }}
{{- end -}}


{{- define "global.jobURL" -}}
{{- $root := .Top | default . -}}
{{- $enableJobs := $root.Values.global.enableJobsUrl | default false -}}
{{- $agents := $root.Values.global.agents | default dict -}}
{{- $url := $agents.url | default "" -}}
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



{{/* One scanner container performs the combined scan and direct HTTP upload. */}}
{{- define "risk-assessment.container" -}}
- name: k8s-risk-assessment
  image: {{ include "kubescape.image" . | quote }}
  imagePullPolicy: IfNotPresent
  command: ["python3", "/usr/local/bin/scan-and-upload.py"]
  resources:
    {{- toYaml .Values.global.job.resources | nindent 4 }}
  env:
    - name: ARTIFACT_URL
      {{- if .Values.global.artifactURL }}
      value: {{ .Values.global.artifactURL | quote }}
      {{- else }}
      value: {{ printf "https://%s/api/v1/artifact/?tenant_id=%s&data_type=KS&label_id=%s&save_to_s3=true" (include "global.jobURL" .) (printf "%v" .Values.global.tenantId | urlquery) (printf "%v" .Values.global.label | urlquery) | quote }}
      {{- end }}
    - name: AUTH_TOKEN_PATH
      value: {{ .Values.authTokenPath | quote }}
    - name: TENANT_ID
      value: {{ .Values.global.tenantId | toString | quote }}
    - name: CLUSTER_NAME
      value: {{ .Values.global.clusterName | quote }}
    - name: CLUSTER_ID
      value: {{ .Values.global.clusterID | toString | quote }}
    - name: LABEL_NAME
      value: {{ .Values.global.label | toString | quote }}
    - name: AIRGAPPED
      value: {{ .Values.global.airgapped | quote }}
    - name: CONTROLS_CONFIG_URL
      value: {{ .Values.global.kraCustomConfig | default "" | quote }}
    - name: SKIP_TLS_VERIFICATION
      value: {{ .Values.global.skipTLSVerification | quote }}
    {{- if .Values.global.certEnabled }}
    - name: CA_PATH
      value: /certs/tls.crt
    - name: CA_URL
      value: {{ .Values.global.certURL | default "" | quote }}
    {{- end }}
  volumeMounts:
    - name: datapath
      mountPath: /data
    - name: secret-volume
      mountPath: /secrets/tokens
      readOnly: true
    {{- if .Values.global.certEnabled }}
    - name: certs
      mountPath: /certs
      readOnly: true
    {{- end }}
{{- end -}}

{{- define "risk-assessment.volumes" -}}
- name: datapath
  emptyDir: {}
- name: secret-volume
  secret:
    secretName: {{ .Values.global.secretName | default "jobs-token" }}
{{- if .Values.global.certEnabled }}
- name: certs
  secret:
    secretName: {{ .Values.global.certSecretName | default "jobs-cert" }}
{{- end }}
{{- end -}}
