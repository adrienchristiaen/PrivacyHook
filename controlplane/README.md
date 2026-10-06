# bodycam control plane

The team side of bodycam: one small service that gives a whole team (or a
data platform group) a shared dashboard of what their AI coding agents do, and
optionally pushes central rules to every developer.

- **Team dashboard** at `/`: active developers, agent sessions, tool calls,
  secrets masked, what would have been blocked, per developer and per tool.
- **Central policy** (optional): a security team writes one `policy.yaml`;
  rules served here are checked before a developer's local `policy.json`, so
  they can't be overridden locally.

Only metadata reaches the server (event type, tool name, agent, developer,
secret categories and counts, policy rule reasons). Commands, file paths,
prompts and secret values never leave developers' machines.

This is a separate deployable from the `bodycam` pip package. The CLI
and hooks stay fully usable (and MIT-licensed) without it.

## Set up a team in two steps

**1. Admin, once:** run the server with a team token.

```bash
docker build -t privacyhook-controlplane -f controlplane/Dockerfile .
docker run -d -p 8957:8957 -v privacyhook-data:/data \
  -e PRIVACYHOOK_CONTROLPLANE_TOKEN=<team-token> privacyhook-controlplane
```

No policy file is needed to start. Put it behind your usual TLS proxy (see
[TLS](#tls)) and share the URL and token with the team.

**2. Each developer, once:**

```bash
bodycam join https://privacyhook.acme.internal --token <team-token>
```

That checks the token, installs the hooks for every detected agent CLI, and
starts sending activity metadata. The developer appears under their OS
username (`--name` to change it). `bodycam status` shows the connection,
`bodycam leave` stops syncing.

Open `https://privacyhook.acme.internal/` and enter the team token to see the
dashboard. Events are queued locally and sent in the background by a
detached process, so a slow or unreachable server never slows down an agent;
queued events are sent once it is back.

## Run locally

```bash
pip install pyyaml
PRIVACYHOOK_CONTROLPLANE_POLICY_PATH=./controlplane/example-policy.yaml \
PRIVACYHOOK_CONTROLPLANE_TOKEN=dev-token \
python -m controlplane.server
```

Point a developer's hook at it:

```bash
bodycam join http://127.0.0.1:8957 --token dev-token
bodycam status   # TEAM: connected
```

`PRIVACYHOOK_CONTROLPLANE_URL` / `PRIVACYHOOK_CONTROLPLANE_TOKEN` env vars
still work and override the saved config (handy for CI runners and managed
laptops).

## Endpoints

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/policy` | GET | Bearer token | Serves the current rule set + a content-hash version |
| `/` | GET | token entered in the page | Team dashboard |
| `/v1/events` | POST | Bearer token, rate-limited (600/min/IP by default — tune via `PRIVACYHOOK_CONTROLPLANE_EVENTS_RATE_LIMIT`) | Receives event metadata, batched as `{"events": [...]}` (or the original single `{action, tool, team, rule_id}`) — never raw commands/paths/secrets |
| `/v1/events` | GET | Bearer token | Recent events for your tenant (`?limit=`, `?user=`) |
| `/v1/summary` | GET | Bearer token | Per-developer, per-tool and per-rule aggregates (`?hours=24`) |
| `/metrics` | GET | none | Prometheus counters (`privacyhook_policy_decisions_total`, labeled `tenant`/`action`/`tool`/`team`) — point Grafana/Datadog at this |
| `/healthz` | GET | none | k8s liveness/readiness probe |

Events are stored in SQLite at `PRIVACYHOOK_CONTROLPLANE_DB` (`/data/events.db`
in the Docker image — mount a volume there to keep history across restarts).

## Grafana dashboard

`controlplane/grafana-dashboard.json` is a ready-to-import dashboard for
the `/metrics` endpoint above: decision rate by action, blocked calls by
tool, decisions by team, and a 24h total — nothing to build yourself.
Import it in Grafana (Dashboards → New → Import), point it at your
Prometheus datasource, and it renders against your existing scrape.

## TLS

The server itself speaks plain HTTP — it's a small stdlib service meant to sit
behind whatever TLS termination your cluster already has. **Do not expose it
directly to the internet without TLS in front of it**: the bearer token and
policy content would otherwise travel in clear text.

- **Kubernetes**: put an Ingress (nginx-ingress, Traefik, etc.) or a service
  mesh (Istio, Linkerd) in front of the `privacyhook-controlplane` Service and
  terminate TLS there — same pattern as any other internal API.
- **Standalone / Docker**: put it behind a reverse proxy (Caddy, nginx, or a
  cloud load balancer) that terminates TLS and forwards plain HTTP to
  `:8957`.
- If every caller is on a private network you fully control (e.g. a VPN-only
  cluster), plain HTTP internally is an acceptable tradeoff — but the token
  is still a bearer secret, treat it like one either way.

## Multi-tenant

The default setup above is single-tenant: one token, one `policy.yaml`. If
you're hosting this control plane on behalf of several distinct clients
(e.g. as a managed service), point `PRIVACYHOOK_CONTROLPLANE_TENANTS_PATH`
at a YAML file instead of setting `_TOKEN`/`_POLICY_PATH` directly:

```yaml
- id: acme
  token: acme-token
  policy_path: /etc/privacyhook/tenants/acme/policy.yaml
- id: globex
  token: globex-token
  policy_path: /etc/privacyhook/tenants/globex/policy.yaml
```

Each tenant's token, policy, and `/metrics` counters are fully isolated —
a request is matched to exactly one tenant by its bearer token, and that
tenant only ever sees its own rules and its own decision counts (labeled
`tenant="acme"` etc. in `/metrics`). Tenant ids and tokens must be unique;
a duplicate of either is rejected at startup. See
`controlplane/k8s/tenants-example.yaml` for the Kubernetes Secret shape.

## Deploy on Kubernetes

### Helm (recommended)

```bash
helm install bodycam oci://ghcr.io/adrienchristiaen/charts/privacyhook-controlplane \
  --namespace bodycam --create-namespace \
  --set token.value=<team-token> \
  --set ingress.enabled=true --set ingress.host=privacyhook.acme.internal \
  --set ingress.tls.secretName=privacyhook-tls
```

The chart lives in [`deploy/helm/privacyhook-controlplane`](../deploy/helm/privacyhook-controlplane);
every option is documented in its `values.yaml`. The main ones:

| Value | What it does |
|---|---|
| `token.value` / `token.existingSecret` | Team token (or a Secret you manage, e.g. via External Secrets / Vault) |
| `postgres.url` / `postgres.existingSecret` | Use Postgres instead of SQLite; required for `replicaCount > 1` |
| `persistence.*` | SQLite PersistentVolume (default, single replica) |
| `ingress.*` | Expose the dashboard and API, with TLS |
| `otlp.endpoint`, `otlp.headersSecret` | Forward events to your OpenTelemetry collector |
| `serviceMonitor.enabled` | Prometheus Operator scraping of `/metrics` |
| `policy.rules` | Central rules pushed to every developer |
| `tenants.existingSecret` | Multi-tenant hosting |

The pod runs as non-root with a read-only root filesystem. The chart refuses
to render `replicaCount > 1` without Postgres.

### Terraform

[`deploy/terraform/privacyhook-controlplane`](../deploy/terraform/privacyhook-controlplane)
wraps the chart in a `helm_release`, with secrets passed as `set_sensitive`:

```hcl
module "bodycam" {
  source = "github.com/adrienchristiaen/PrivacyHook//deploy/terraform/privacyhook-controlplane"

  team_token    = var.team_token
  postgres_url  = var.postgres_url      # optional: HA mode
  replica_count = 2

  ingress_host    = "privacyhook.acme.internal"
  ingress_class   = "nginx"
  tls_secret_name = "privacyhook-tls"
  otlp_endpoint   = "http://otel-collector.observability:4318"
}

output "join_command" { value = module.privacyhook.join_command }
```

A complete example is in `examples/eks-with-postgres`. The module expects you
to configure the `helm` provider for your cluster.

### Plain manifests

`controlplane/k8s/` keeps minimal manifests for clusters without Helm:

```bash
kubectl create secret generic privacyhook-controlplane-token --from-literal=token=<your-token>
kubectl apply -f controlplane/k8s/configmap-example.yaml
kubectl apply -f controlplane/k8s/pvc.yaml
kubectl apply -f controlplane/k8s/deployment.yaml
kubectl apply -f controlplane/k8s/service.yaml
```

To update policy: edit the ConfigMap and re-apply. The server picks up the
change on the next `/v1/policy` request (checked via file mtime — no
restart needed).

## Images

`ghcr.io/adrienchristiaen/privacyhook-controlplane` is published by
`.github/workflows/release.yml` for `linux/amd64` and `linux/arm64`: `:main`
on every push to `main`, `:<version>` and `:latest` on a `v*` tag (which also
publishes the Helm chart to `oci://ghcr.io/adrienchristiaen/charts`).

## Storage and high availability

| | SQLite (default) | Postgres |
|---|---|---|
| Configure | nothing (`PRIVACYHOOK_CONTROLPLANE_DB`, default `/data/events.db` in the image) | `PRIVACYHOOK_CONTROLPLANE_DATABASE_URL=postgresql://…` |
| Replicas | 1 | as many as you like |
| Good for | one team, a few dozen developers | larger orgs, HA, managed DB backups |

The schema is created on startup; Postgres connections reconnect
automatically after a failover.

## Plug into your data platform

**Prometheus / Grafana / Datadog** — scrape `/metrics`
(`privacyhook_policy_decisions_total{tenant,action,tool,team}`; `action` is the
event type, including `tool_call` and `would_block`). Import
`controlplane/grafana-dashboard.json` for a ready-made Grafana dashboard.

**OpenTelemetry** — set `PRIVACYHOOK_CONTROLPLANE_OTLP_ENDPOINT` (or the
standard `OTEL_EXPORTER_OTLP_ENDPOINT`) to an OTLP/HTTP collector. Every event
is forwarded as a log record (`service.name=bodycam-server`;
attributes `bodycam.event`, `bodycam.tool`, `bodycam.cli`,
`privacyhook.rule`, `privacyhook.secret_categories`, `enduser.id`,
`session.id`, …; severity WARN for would-block, ERROR for blocks). Headers such
as API keys go in `PRIVACYHOOK_CONTROLPLANE_OTLP_HEADERS="key=value,…"`.

**Warehouse (BigQuery, Snowflake, Databricks, …)** — `GET /v1/export` returns
raw events as NDJSON (default) or CSV (`?format=csv`). It is incremental: the
`X-Next-After-Id` response header is where the next run resumes.

```bash
# nightly job: append new events to BigQuery
AFTER=$(cat .last_id 2>/dev/null || echo 0)
curl -sfD headers.txt -H "Authorization: Bearer $TOKEN" \
  "https://privacyhook.acme.internal/v1/export?after_id=$AFTER&limit=100000" > events.ndjson
grep -i '^x-next-after-id' headers.txt | tr -d '\r' | awk '{print $2}' > .last_id
bq load --source_format=NEWLINE_DELIMITED_JSON --autodetect security.agent_events events.ndjson
```

Also accepted: `since` / `until` (Unix seconds) and `limit` (max 100000).

**Your own panel** — `GET /v1/summary?hours=24` and `GET /v1/events?limit=&user=`
return the same JSON the built-in dashboard uses.

**Developer fleets and CI** — instead of `bodycam join`, managed laptops
(MDM) and CI runners can set `PRIVACYHOOK_CONTROLPLANE_URL`,
`PRIVACYHOOK_CONTROLPLANE_TOKEN` and optionally `PRIVACYHOOK_USER`.
