"""Generate the StreamIntel product-metrics Grafana dashboard (Postgres datasource)."""

import json

DS = {"type": "postgres", "uid": "streamintel-pg"}
panels = []
_id = 0
y = 0


def nid():
    global _id
    _id += 1
    return _id


def row(title):
    global y
    panels.append(
        {
            "id": nid(),
            "type": "row",
            "title": title,
            "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        }
    )
    y += 1


def target(sql, fmt):
    return {
        "refId": "A",
        "datasource": DS,
        "rawSql": sql,
        "rawQuery": True,
        "format": fmt,
    }


def stat(title, sql, unit="short", w=6, h=5, x=0, color="blue"):
    return {
        "id": nid(),
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, "table")],
        "fieldConfig": {
            "defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color}},
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": ""},
            "colorMode": "value",
            "graphMode": "area",
        },
    }


def ts(title, sql, unit="short", w=12, h=8, x=0):
    return {
        "id": nid(),
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, "time_series")],
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"fillOpacity": 15, "showPoints": "auto"},
            },
            "overrides": [],
        },
    }


def barcat(title, sql, unit="short", w=12, h=8, x=0, ptype="barchart"):
    return {
        "id": nid(),
        "type": ptype,
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
    }


def table(title, sql, w=12, h=8, x=0):
    return {
        "id": nid(),
        "type": "table",
        "title": title,
        "datasource": DS,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


# ---------- Visao geral (lifetime KPIs) ----------
row("Visao geral do produto")
panels += [
    stat(
        "Canais (streamers)", "select count(*) from channels", w=6, x=0, color="purple"
    ),
    stat(
        "Streams processadas (READY)",
        "select count(*) from streams where status = 'ready'",
        w=6,
        x=6,
        color="green",
    ),
    stat("Streams (total)", "select count(*) from streams", w=6, x=12, color="blue"),
    stat(
        "Horas de stream capturadas",
        "select coalesce(sum(extract(epoch from (coalesce(ended_at, started_at) - started_at)))/3600.0, 0) from streams",
        unit="h",
        w=6,
        x=18,
        color="blue",
    ),
]
y += 5
panels += [
    stat(
        "Mensagens de chat",
        "select count(*) from chat_messages",
        w=6,
        x=0,
        color="orange",
    ),
    stat(
        "Chatters unicos",
        "select count(distinct author_id) from chat_messages",
        w=6,
        x=6,
        color="orange",
    ),
    stat(
        "Insights gerados (IA)",
        "select count(*) from insights",
        w=6,
        x=12,
        color="purple",
    ),
    stat(
        "Tokens LLM (in+out)",
        "select coalesce(sum(tokens_in + tokens_out), 0) from insights",
        w=6,
        x=18,
        color="red",
    ),
]
y += 5

# ---------- Pipeline ----------
row("Pipeline de processamento")
panels.append(
    barcat(
        "Streams por status",
        "select status as metric, count(*) as value from streams group by status order by value desc",
        w=8,
        x=0,
        ptype="piechart",
    )
)
panels.append(
    ts(
        "Streams por dia",
        "select $__timeGroup(started_at, '1d') as time, count(*) as \"streams\" from streams where $__timeFilter(started_at) group by 1 order by 1",
        w=16,
        x=8,
    )
)
y += 8
panels.append(
    stat(
        "Taxa de falha de jobs",
        "select coalesce(round(100.0 * count(*) filter (where status = 'failed') / nullif(count(*), 0), 1), 0) from jobs",
        unit="percent",
        w=6,
        x=0,
        color="red",
    )
)
panels.append(
    table(
        "Jobs por tipo e status",
        'select type as "tipo", status, count(*) as "qtd", round(avg(extract(epoch from (finished_at - started_at)))::numeric, 1) as "seg_medio" from jobs group by type, status order by type, status',
        w=18,
        x=6,
    )
)
y += 8

# ---------- Engajamento ----------
row("Engajamento da audiencia")
panels.append(
    ts(
        "Mensagens de chat por dia",
        "select $__timeGroup(sent_at, '1d') as time, count(*) as \"mensagens\" from chat_messages where $__timeFilter(sent_at) group by 1 order by 1",
        w=12,
        x=0,
    )
)
panels.append(
    ts(
        "Viewers medios (por hora)",
        "select $__timeGroup(sampled_at, '1h') as time, avg(viewer_count) as \"viewers\" from viewer_samples where $__timeFilter(sampled_at) group by 1 order by 1",
        w=12,
        x=12,
    )
)
y += 8
panels.append(
    stat(
        "Pico de viewers",
        "select coalesce(max(viewer_count), 0) from viewer_samples",
        w=6,
        x=0,
        color="green",
    )
)
panels.append(
    barcat(
        "Eventos por tipo (subs, doacoes...)",
        "select type as metric, count(*) as value from events group by type order by value desc",
        w=18,
        x=6,
    )
)
y += 8

# ---------- Conteudo analisado ----------
row("Conteudo analisado (transcricao + IA)")
panels += [
    stat(
        "Segmentos transcritos",
        "select count(*) from transcript_segments",
        w=6,
        x=0,
        color="blue",
    ),
    stat(
        "Horas de fala transcritas",
        "select coalesce(sum(extract(epoch from (ended_at - started_at)))/3600.0, 0) from transcript_segments where kind = 'speech'",
        unit="h",
        w=6,
        x=6,
        color="blue",
    ),
]
panels.append(
    barcat(
        "Segmentos por tipo",
        "select kind as metric, count(*) as value from transcript_segments group by kind order by value desc",
        w=12,
        x=12,
    )
)
y += 5
panels.append(
    table(
        "Insights por tipo (com feedback)",
        'select type as "tipo", count(*) as "qtd", count(*) filter (where feedback = \'useful\') as "util", count(*) filter (where feedback = \'not_useful\') as "nao_util" from insights group by type order by "qtd" desc',
        w=24,
        x=0,
    )
)
y += 8

dash = {
    "uid": "streamintel-product",
    "title": "StreamIntel - Produto",
    "tags": ["streamintel", "produto"],
    "timezone": "browser",
    "schemaVersion": 39,
    "refresh": "5m",
    "time": {"from": "now-30d", "to": "now"},
    "panels": panels,
}

with open(
    "/private/tmp/claude-501/-Users-iklo-twitch/fd1bdbc2-ee4e-4907-9d48-0dd3d3406339/scratchpad/streamintel-product.json",
    "w",
) as f:
    json.dump(dash, f, indent=2)
print(
    "panels:",
    len([p for p in panels if p["type"] != "row"]),
    "rows:",
    len([p for p in panels if p["type"] == "row"]),
)
