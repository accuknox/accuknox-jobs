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



{{/* Scanner init container, followed by the knoxjobs artifact container. */}}
{{- define "risk-assessment.container" -}}
- name: k8s-risk-assessment
  image: {{ include "kubescape.image" . | quote }}
  imagePullPolicy: {{ .Values.kubescape.pullPolicy | default "Always" }}
  command: ["python3", "/usr/local/bin/scan-resources.py"]
  resources:
    {{- toYaml .Values.global.job.resources | nindent 4 }}
  env:
    - name: NAMESPACE_CONCURRENCY
      valueFrom:
        configMapKeyRef:
          name: {{ .Release.Name }}-namespace-scan-config
          key: NAMESPACE_CONCURRENCY
    - name: CLUSTER_NAME
      value: {{ .Values.global.clusterName | quote }}
    - name: AIRGAPPED
      value: {{ .Values.global.airgapped | quote }}
    - name: CONTROLS_CONFIG_URL
      value: {{ .Values.global.kraCustomConfig | default "" | quote }}
    - name: SKIP_TLS_VERIFICATION
      value: {{ .Values.global.skipTLSVerification | quote }}
    {{- if .Values.global.certEnabled }}
    - name: CA_PATH
      value: /certs/tls.crt
    {{- end }}
  volumeMounts:
    - name: datapath
      mountPath: /data
    - name: scanner-config
      mountPath: /data/config
      readOnly: true
    {{- if .Values.global.certEnabled }}
    - name: certs
      mountPath: /certs
      readOnly: true
    {{- end }}
{{- end -}}

{{- define "risk-assessment.uploader" -}}
- name: artifact-api-container
  image: {{ .Values.knoxjobs.image | quote }}
  imagePullPolicy: {{ .Values.knoxjobs.pullPolicy | quote }}
  command: ["/bin/sh", "/data/config/upload-reports.sh"]
  env:
    - name: KNOXJOBS_BINARY
      value: {{ .Values.knoxjobs.binaryPath | quote }}
  resources:
    {{- toYaml .Values.knoxjobs.resources | nindent 4 }}
  volumeMounts:
    - name: datapath
      mountPath: /data
    - name: scanner-config
      mountPath: /data/config
      readOnly: true
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
- name: scanner-config
  configMap:
    name: {{ .Release.Name }}-namespace-scan-config
- name: secret-volume
  secret:
    secretName: {{ .Values.global.secretName | default "jobs-token" }}
{{- if .Values.global.certEnabled }}
- name: certs
  secret:
    secretName: {{ .Values.global.certSecretName | default "jobs-cert" }}
{{- end }}
{{- end -}}
