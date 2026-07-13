# Monitoring

streamintel reuses the existing `financialdata-monitoring` droplet
(`165.227.70.198`, VPC `10.108.0.5`) which runs Prometheus + Grafana +
blackbox + node-exporter. Grafana is on `:3000` (firewall-limited).
Both droplets share the private VPC `10.108.0.x`.

## What is monitored

| Layer | Source | Where |
|-------|--------|-------|
| Uptime / TLS | blackbox probes `streamintel.cc` + `/healthz` | monitoring `prometheus.yml` |
| Host CPU/mem/disk | `node-exporter` on stream-intel | `deploy/monitoring-agent.yml` |
| Pipeline backlog (`jobs:transcribe/analyze`) | `redis_exporter` `--check-streams` | `deploy/monitoring-agent.yml` |
| API req rate / latency / 5xx | app `/metrics` (token) | `apps/api/metrics.py` |
| Postgres (managed cluster) | DO native metrics `:9273` | already scraped (shared cluster) |

### Known limitation: per-container CPU/mem by name

cadvisor runs on the box but cannot resolve container names on this host: the
Docker daemon uses the containerd `overlayfs` image store, which cadvisor
v0.49.1 cannot map to names (it sees the container cgroups only by hash id).
So there are no `name="deploy-*"` per-container panels. Worker liveness is
instead covered by the Valkey backlog alert (a dead/stuck consuming worker
stops draining its stream). The capture worker (a producer, no queue) is not
directly covered; a per-worker heartbeat metric would close that gap.

To get named per-container metrics, switch the box to the `overlay2` storage
driver (daemon.json + `systemctl restart docker`, brief container restart).

## Alerts (6 rules, Grafana-provisioned)

site-down, host-down (node-exporter gone), disk >85%, queue backlog,
API 5xx, TLS <14 days. Removing a rule from the file does not delete it in
Grafana; use the `deleteRules:` block (see `streamintel-alerts.yml`).

## Exporters on the stream-intel box

`deploy/monitoring-agent.yml` runs standalone (decoupled from the app stack so
app redeploys don't disturb it). All metrics ports bind to the private VPC IP
`10.108.0.3` only (the droplet has no cloud firewall):

```
scp deploy/monitoring-agent.yml root@stream-intel:/opt/streamintel-monitoring/docker-compose.yml
ssh root@stream-intel 'cd /opt/streamintel-monitoring && docker compose up -d'
```

## App /metrics

`GET /metrics` returns Prometheus HTTP metrics, guarded by a bearer token.
Set `METRICS_TOKEN` in the app `.env`; the same value is the `authorization`
credential in the monitoring box's `streamintel-app` scrape job. Empty token =
endpoint returns 404 (closed).

## Product metrics dashboard (Postgres, not Prometheus)

Product analytics (active channels, streams processed, hours captured/transcribed,
chat volume, viewers, events, insights + LLM token spend, job throughput) come
from the app Postgres DB directly via a Grafana **Postgres datasource**, not from
Prometheus. This is the source of truth and survives app redeploys.

- Dashboard: "StreamIntel - Produto" (`streamintel-product`), 20 SQL panels.
  Regenerate with `deploy/monitoring/gen_product.py`.
- Datasource: `StreamIntel DB` (uid `streamintel-pg`), read-only user `grafana_ro`
  scoped to the `streamintel` DB. See `streamintel-pg-datasource.example.yml`
  (fill `GRAFANA_RO_PASSWORD`; the real file with the secret lives only on the box).

`grafana_ro` was created on the managed cluster with `GRANT SELECT` only (plus
default privileges for future `chat_messages` partitions); it cannot write.

## App /metrics is redeployed away

`apps/api/metrics.py` (`/metrics`) lives on this branch but the box deploys from
another branch, so a redeploy of the app reverts the `/metrics` route. Merge this
branch into the deploying branch to make the `streamintel-app` Prometheus scrape
stick. Product metrics above do NOT depend on it.

## Monitoring box config (lives on that droplet, not here)

- `/opt/monitoring/prometheus.yml` - `streamintel-*` scrape jobs + blackbox targets
- `/opt/monitoring/grafana/provisioning/dashboards/streamintel.json` - dashboard
- `/opt/monitoring/grafana/provisioning/alerting/streamintel.yml` - 7 alert rules

Reload Prometheus: `docker kill -s HUP monitoring-prometheus-1`.
Reload Grafana provisioning: `docker restart monitoring-grafana-1`.
