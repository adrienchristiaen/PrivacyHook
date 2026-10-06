locals {
  values = {
    replicaCount = var.replica_count
    image        = { tag = var.image_tag }
    token = {
      existingSecret = var.team_token_secret
    }
    postgres = {
      existingSecret = var.postgres_secret
    }
    persistence = {
      size         = var.storage_size
      storageClass = var.storage_class
    }
    policy = { rules = var.policy_rules }
    otlp = {
      endpoint      = var.otlp_endpoint
      headersSecret = var.otlp_headers_secret
    }
    ingress = {
      enabled     = var.ingress_host != ""
      host        = var.ingress_host
      className   = var.ingress_class
      annotations = var.ingress_annotations
      tls         = { secretName = var.tls_secret_name }
    }
    serviceMonitor = { enabled = var.service_monitor }
  }
}

resource "helm_release" "this" {
  name             = var.name
  namespace        = var.namespace
  create_namespace = var.create_namespace
  chart            = var.chart
  version          = var.chart_version

  values = compact([yamlencode(local.values), var.extra_values])

  # Secrets go through set_sensitive so they never appear in plan output.
  # An empty value leaves the chart on the *_secret / SQLite defaults.
  set_sensitive {
    name  = "token.value"
    value = var.team_token == null ? "" : var.team_token
  }

  set_sensitive {
    name  = "postgres.url"
    value = var.postgres_url == null ? "" : var.postgres_url
  }

  lifecycle {
    precondition {
      condition     = var.team_token != null || var.team_token_secret != ""
      error_message = "Set team_token or team_token_secret."
    }
    precondition {
      condition     = var.replica_count == 1 || var.postgres_url != null || var.postgres_secret != ""
      error_message = "replica_count > 1 requires postgres_url or postgres_secret (SQLite supports a single replica)."
    }
  }
}
