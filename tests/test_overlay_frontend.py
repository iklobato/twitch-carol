from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIWebSocketRoute

from alerts import AlertKind, StreamAlert
from web import build_app

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_HTML = (REPO_ROOT / "overlay.html").read_text(encoding="utf-8")
OVERLAY_JS = (REPO_ROOT / "static" / "overlay.js").read_text(encoding="utf-8")


def test_html_has_required_element_ids():
    for element_id in ("alert", "headline", "detail"):
        assert f'id="{element_id}"' in OVERLAY_HTML


def test_html_loads_the_extracted_script():
    assert '<script src="/static/overlay.js"></script>' in OVERLAY_HTML


def test_js_reads_only_fields_the_server_sends():
    payload_keys = set(
        StreamAlert(kind=AlertKind.GIFT, headline="h", detail="d").to_payload()
    )
    js_fields = set(re.findall(r"alert\.(\w+)", OVERLAY_JS))
    assert js_fields <= payload_keys
    assert {"kind", "headline", "detail"} <= js_fields


def test_js_websocket_path_matches_app_route(make_settings, hub, recording_hub):
    assert "/ws" in OVERLAY_JS
    app = build_app(hub, recording_hub, make_settings())
    ws_paths = [r.path for r in app.routes if isinstance(r, APIWebSocketRoute)]
    assert ws_paths == ["/ws"]


def test_css_kind_classes_are_valid_alert_kinds():
    # Kind selectors must ride on #alert: a bare class selector loses the
    # box-shadow specificity fight against the `#alert` base rule.
    styled_kinds = set(re.findall(r"#alert\.([a-z_]+)\s*\{", OVERLAY_HTML)) - {"show"}
    kind_values = {kind.value for kind in AlertKind}
    assert styled_kinds and styled_kinds <= kind_values
    assert not re.findall(r"\n\s*\.([a-z_]+)\s*\{", OVERLAY_HTML)


def test_js_guards_json_parse_and_reconnects():
    assert "try {" in OVERLAY_JS and "JSON.parse" in OVERLAY_JS
    assert re.search(r"onclose\s*=\s*\(\)\s*=>\s*setTimeout\(connect", OVERLAY_JS)
