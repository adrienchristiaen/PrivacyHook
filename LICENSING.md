# Licensing strategy

This repository has two licenses, split by directory:

**`privacyhook/` (the CLI, hooks, local policy engine, audit log, `monitor.py`
dashboard) — MIT** (see [`LICENSE`](LICENSE)). Free for any use, forever, no
restrictions. This is the wedge product: install it, run it locally, get value
with zero setup.

**`controlplane/` (the centralized policy server — YAML policy distribution,
`/v1/policy`, `/metrics`, k8s deployment) — [Business Source License 1.1](https://mariadb.com/bsl11/)**
(see [`controlplane/LICENSE`](controlplane/LICENSE)), following the same model
as projects like [caveman](https://github.com/JuliusBrussee/caveman):

- **Free for:** internal evaluation, development, testing, and production
  self-hosted use — including inside a company, for that company's own
  team(s) and traffic. A security team can run this on their own pod, for
  their own developers, at no cost.
- **Restricted:** offering the licensed component to third parties as a
  hosted or managed service (i.e. reselling it as a SaaS product competing
  with the Licensor's own hosted offering) requires a commercial agreement
  with the Licensor.
- **Change Date:** 2030-09-06 (4 years after first release). On that date,
  `controlplane/` automatically relicenses to Apache License 2.0 — fully
  open source, no strings attached.

A further, fully proprietary layer (hosted multi-tenant SaaS: managed
dashboards, alerting, long-term audit history, billing) is planned as a
**separate, private repository** — never open-sourced, not part of this
project. That is the paid hosted product; `controlplane/` above is what you'd
self-host instead if you don't want to pay for hosting.
