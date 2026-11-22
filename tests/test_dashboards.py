"""Dashboard spec validation and the dashboard tool path (create / update / add / remove)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hearthly import tools
from hearthly.spec import DashboardSpec, auto_layout
from hearthly.state import StateStore
from hearthly.validate import SpecError

from .helpers import REFUNDS_BY_REASON_SQL, WEEKLY_REVENUE_SQL, sample_spec


def test_create_and_get(state_db: Path) -> None:
    out = tools.create_dashboard(sample_spec())
    assert out["version"] == 1 and out["url"].endswith("/dynamic#test-dash")
    assert {p["id"] for p in out["panels"]} == {"rev-kpi", "rev-trend", "refund-reasons"}
    assert all(p["rows"] > 0 for p in out["panels"])
    got = tools.get_dashboard("test-dash")
    assert len(got["spec"]["layout"]) == 3
    assert got["history"][0]["change"] == "created"
    # spec stores SQL, never data
    assert "rows" not in got["spec"]["panels"][0]


def test_auto_layout_kpi_first_row() -> None:
    spec = auto_layout(DashboardSpec.model_validate(sample_spec()))
    kpi = next(i for i in spec.layout if i.panel_id == "rev-kpi")
    assert (kpi.x, kpi.y, kpi.w, kpi.h) == (0, 0, 3, 2)
    assert all(i.x + i.w <= 12 for i in spec.layout)


def test_duplicate_create_rejected(state_db: Path) -> None:
    tools.create_dashboard(sample_spec())
    with pytest.raises(tools.ToolInputError, match="already exists"):
        tools.create_dashboard(sample_spec())
    assert tools.create_dashboard(sample_spec(), replace=True)["version"] == 2


def _bad(**panel_changes: object) -> dict:
    spec = sample_spec()
    spec["panels"][1].update(panel_changes)
    return spec


@pytest.mark.parametrize("spec,expected", [
    (_bad(encoding={"x": "week", "y": "revenu"}), "encoding.y = 'revenu' is not a column"),
    (_bad(encoding={"x": "week"}), "encoding.y is required"),
    (_bad(sql="SELECT nope FROM orders"), "describe_schema"),
    (_bad(sql="DELETE FROM orders"), "Only read-only SELECT"),
    (_bad(sql="SELECT id, id AS v FROM order_items", encoding={"x": "id", "y": "v"}), "more than 5000 rows"),
    (_bad(encoding={"x": "revenue", "y": "week"}), "must be numeric"),
])
def test_validation_errors_are_actionable(state_db: Path, spec: dict, expected: str) -> None:
    with pytest.raises(SpecError) as exc:
        tools.create_dashboard(spec)
    assert expected in str(exc.value)
    assert "Result columns" in str(exc.value) or expected in ("describe_schema", "Only read-only SELECT",
                                                              "more than 5000 rows", "must be numeric")
    assert not StateStore().exists("test-dash")


def test_all_errors_reported_at_once(state_db: Path) -> None:
    spec = sample_spec()
    spec["panels"][0]["encoding"] = {"value": "nope"}
    spec["panels"][2]["sql"] = "SELECT missing FROM refunds"
    with pytest.raises(SpecError) as exc:
        tools.create_dashboard(spec)
    assert len(exc.value.errors) == 2


def test_structural_validation() -> None:
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate({**sample_spec(), "id": "Not A Slug"})
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate({**sample_spec(), "panels": []})
    bad = sample_spec()
    bad["panels"][0]["type"] = "pie3d"
    with pytest.raises(ValidationError):
        DashboardSpec.model_validate(bad)


def test_duplicate_panel_ids(state_db: Path) -> None:
    spec = sample_spec()
    spec["panels"][1]["id"] = "rev-kpi"
    with pytest.raises(SpecError, match="duplicate panel ids"):
        tools.create_dashboard(spec)


def test_overlapping_layout_is_reflowed(state_db: Path) -> None:
    spec = sample_spec()
    spec["layout"] = [{"panel_id": "rev-trend", "x": 0, "y": 0, "w": 6, "h": 4},
                      {"panel_id": "refund-reasons", "x": 2, "y": 1, "w": 6, "h": 4}]
    out = tools.create_dashboard(spec)
    assert any("overlapped" in w for w in out["warnings"])


def test_update_patch_merges(state_db: Path) -> None:
    tools.create_dashboard(sample_spec())
    out = tools.update_dashboard("test-dash", {
        "title": "Renamed",
        "panels": [{"id": "rev-trend", "type": "area", "encoding": {"format": "number"}},
                   {"id": "refunds-bar", "type": "horizontal_bar", "title": "Refunds by reason",
                    "sql": REFUNDS_BY_REASON_SQL, "encoding": {"x": "reason", "y": "requests"}}],
    })
    assert out["version"] == 2 and out["title"] == "Renamed"
    spec = tools.get_dashboard("test-dash")["spec"]
    trend = next(p for p in spec["panels"] if p["id"] == "rev-trend")
    assert trend["type"] == "area" and trend["encoding"]["y"] == "revenue" and trend["encoding"]["format"] == "number"
    assert [p["id"] for p in spec["panels"]][-1] == "refunds-bar"


def test_update_errors(state_db: Path) -> None:
    tools.create_dashboard(sample_spec())
    with pytest.raises(tools.ToolInputError, match="needs type, title, sql"):
        tools.update_dashboard("test-dash", {"panels": [{"id": "brand-new"}]})
    with pytest.raises(tools.ToolInputError, match="No dashboard"):
        tools.update_dashboard("missing", {"title": "x"})
    with pytest.raises(tools.ToolInputError, match="empty"):
        tools.update_dashboard("test-dash", {})
    with pytest.raises(SpecError):
        tools.update_dashboard("test-dash", {"panels": [{"id": "rev-trend", "sql": "SELECT 1 AS one"}]})
    assert tools.get_dashboard("test-dash")["spec"]["version"] == 1, "failed update must not save"


def test_add_and_remove_panel(state_db: Path) -> None:
    tools.create_dashboard(sample_spec())
    out = tools.add_panel("test-dash", {"id": "rev-table", "type": "table", "title": "Weekly revenue table",
                                        "sql": WEEKLY_REVENUE_SQL, "insight": "Exact values."},
                          {"x": 0, "y": 10, "w": 12, "h": 4})
    assert out["version"] == 2
    item = next(i for i in out["layout"] if i["panel_id"] == "rev-table")
    assert (item["y"], item["w"]) == (10, 12)
    with pytest.raises(tools.ToolInputError, match="already exists"):
        tools.add_panel("test-dash", {"id": "rev-table", "type": "table", "title": "x", "sql": "SELECT 1 AS a"})
    out = tools.remove_panel("test-dash", "rev-table")
    assert out["version"] == 3 and len(out["panels"]) == 3
    with pytest.raises(tools.ToolInputError):
        tools.remove_panel("test-dash", "rev-table")


def test_activity_log_records_calls(state_db: Path) -> None:
    tools.run_query("SELECT COUNT(*) FROM orders")
    with pytest.raises(Exception):
        tools.run_query("DROP TABLE orders")
    tools.create_dashboard(sample_spec())
    log = StateStore().activity_since(0)
    assert [r["tool"] for r in log] == ["run_query", "run_query", "create_dashboard"]
    assert log[0]["status"] == "ok" and log[0]["rows"] == 1 and log[0]["sql"].startswith("SELECT")
    assert log[1]["status"] == "error" and "read-only" in log[1]["error"]
    assert log[2]["dashboard_id"] == "test-dash" and log[2]["detail"]["panels"]


def test_list_dashboards(state_db: Path) -> None:
    tools.create_dashboard(sample_spec("a-dash"))
    tools.create_dashboard(sample_spec("b-dash"))
    ids = [d["id"] for d in tools.list_dashboards()["dashboards"]]
    assert set(ids) == {"a-dash", "b-dash"}
