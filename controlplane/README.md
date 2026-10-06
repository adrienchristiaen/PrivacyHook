# privacyhook control plane

The team side of privacyhook: one small service that gives a whole team (or a
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

This is a separate deployable from the `privacyhook` pip package. The CLI
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
privacyhook join https://privacyhook.acme.internal --token <team-token>
```

That checks the token, installs the hooks for every detected agent CLI, and
starts sending activity metadata. The developer appears under their OS
username (`--name` to change it). `privacyhook status` shows the connection,
`privacyhook leave` stops syncing.

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
privacyhook join http://127.0.0.1:8957 --token dev-token
privacyhook status   # TEAM: connected
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

```bash
docker build -t privacyhook-controlplane:latest -f controlplane/Dockerfile .
kubectl create secret generic privacyhook-controlplane-token --from-literal=token=<your-token>
kubectl apply -f controlplane/k8s/configmap-example.yaml
kubectl apply -f controlplane/k8s/deployment.yaml
kubectl apply -f controlplane/k8s/service.yaml
```

To update policy: edit the ConfigMap and re-apply. The server picks up the
change on the next `/v1/policy` request (checked via file mtime — no
restart needed).
