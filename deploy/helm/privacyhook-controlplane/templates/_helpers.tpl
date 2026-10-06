{{- define "ph.name" -}}privacyhook-controlplane{{- end -}}

{{- define "ph.fullname" -}}
{{- if contains "privacyhook" .Release.Name -}}{{ .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-privacyhook" .Release.Name | trunc 63 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "ph.labels" -}}
app.kubernetes.io/name: {{ include "ph.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "ph.selector" -}}
app.kubernetes.io/name: {{ include "ph.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "ph.usesPostgres" -}}
{{- if or .Values.postgres.url .Values.postgres.existingSecret }}true{{ end -}}
{{- end -}}

{{- define "ph.tokenSecret" -}}
{{- .Values.token.existingSecret | default (printf "%s-token" (include "ph.fullname" .)) -}}
{{- end -}}

{{- define "ph.validate" -}}
{{- if and (gt (int .Values.replicaCount) 1) (not (include "ph.usesPostgres" .)) -}}
{{- fail "replicaCount > 1 needs postgres.url or postgres.existingSecret (SQLite supports a single replica)" -}}
{{- end -}}
{{- if not (or .Values.token.value .Values.token.existingSecret .Values.tenants.existingSecret) -}}
{{- fail "set token.value, token.existingSecret or tenants.existingSecret" -}}
{{- end -}}
{{- if and .Values.ingress.enabled (not .Values.ingress.host) -}}
{{- fail "ingress.enabled needs ingress.host" -}}
{{- end -}}
{{- end -}}
