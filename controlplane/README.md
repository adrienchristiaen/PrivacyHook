# holdthedoor control plane

Centralized policy for teams: a security team writes one `policy.yaml`,
deploys this service on a pod, and every developer's local `holdthedoor`
hook pulls it live. Rules served here are authoritative — they're checked
before a developer's local `policy.json`, so they can't be overridden
locally.

This is a separate deployable from the `holdthedoor` pip package. The CLI
and hooks stay fully usable (and MIT-licensed) without this — it's opt-in
via two env vars on the client side.

## Run locally

```bash
pip install pyyaml
HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH=./controlplane/example-policy.yaml \
HOLDTHEDOOR_CONTROLPLANE_TOKEN=dev-token \
python -m controlplane.server
```

Point a developer's hook at it:

```bash
export HOLDTHEDOOR_CONTROLPLANE_URL=http://127.0.0.1:8957
export HOLDTHEDOOR_CONTROLPLANE_TOKEN=dev-token
holdthedoor status   # shows "CONTROL PLANE: connected"
```

## Endpoints

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v1/policy` | GET | Bearer token | Serves the current rule set + a content-hash version |
| `/v1/events` | POST | Bearer token, rate-limited (60/min/IP by default — tune via `HOLDTHEDOOR_CONTROLPLANE_EVENTS_RATE_LIMIT`) | Receives decision metadata (`action`, `tool`, `team`, `rule_id`) — never raw commands/paths/secrets |
| `/metrics` | GET | none | Prometheus counters, labeled by tenant — point Grafana/Datadog at this, no custom dashboard required |
| `/healthz` | GET | none | k8s liveness/readiness probe |

## TLS

The server itself speaks plain HTTP — it's a small stdlib service meant to sit
behind whatever TLS termination your cluster already has. **Do not expose it
directly to the internet without TLS in front of it**: the bearer token and
policy content would otherwise travel in clear text.

- **Kubernetes**: put an Ingress (nginx-ingress, Traefik, etc.) or a service
  mesh (Istio, Linkerd) in front of the `holdthedoor-controlplane` Service and
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
(e.g. as a managed service), point `HOLDTHEDOOR_CONTROLPLANE_TENANTS_PATH`
at a YAML file instead of setting `_TOKEN`/`_POLICY_PATH` directly:

```yaml
- id: acme
  token: acme-token
  policy_path: /etc/holdthedoor/tenants/acme/policy.yaml
- id: globex
  token: globex-token
  policy_path: /etc/holdthedoor/tenants/globex/policy.yaml
```

Each tenant's token, policy, and `/metrics` counters are fully isolated —
a request is matched to exactly one tenant by its bearer token, and that
tenant only ever sees its own rules and its own decision counts (labeled
`tenant="acme"` etc. in `/metrics`). Tenant ids and tokens must be unique;
a duplicate of either is rejected at startup. See
`controlplane/k8s/tenants-example.yaml` for the Kubernetes Secret shape.

## Deploy on Kubernetes

```bash
docker build -t holdthedoor-controlplane:latest -f controlplane/Dockerfile .
kubectl create secret generic holdthedoor-controlplane-token --from-literal=token=<your-token>
kubectl apply -f controlplane/k8s/configmap-example.yaml
kubectl apply -f controlplane/k8s/deployment.yaml
kubectl apply -f controlplane/k8s/service.yaml
```

To update policy: edit the ConfigMap and re-apply. The server picks up the
change on the next `/v1/policy` request (checked via file mtime — no
restart needed).
