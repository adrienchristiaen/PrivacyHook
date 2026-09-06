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
| `/v1/events` | POST | Bearer token | Receives decision metadata (`action`, `tool`, `team`, `rule_id`) — never raw commands/paths/secrets |
| `/metrics` | GET | none | Prometheus counters — point Grafana/Datadog at this, no custom dashboard required |
| `/healthz` | GET | none | k8s liveness/readiness probe |

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
