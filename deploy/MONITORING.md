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
| Per-container CPU/mem/restarts | `cadvisor` on stream-intel | `deploy/monitoring-agent.yml` |
| Pipeline backlog (`jobs:transcribe/analyze`) | `redis_exporter` `--check-streams` | `deploy/monitoring-agent.yml` |
| API req rate / latency / 5xx | app `/metrics` (token) | `apps/api/metrics.py` |
| Postgres (managed cluster) | DO native metrics `:9273` | already scraped (shared cluster) |

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

## Monitoring box config (lives on that droplet, not here)

- `/opt/monitoring/prometheus.yml` - `streamintel-*` scrape jobs + blackbox targets
- `/opt/monitoring/grafana/provisioning/dashboards/streamintel.json` - dashboard
- `/opt/monitoring/grafana/provisioning/alerting/streamintel.yml` - 7 alert rules

Reload Prometheus: `docker kill -s HUP monitoring-prometheus-1`.
Reload Grafana provisioning: `docker restart monitoring-grafana-1`.
