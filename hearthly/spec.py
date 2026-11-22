"""Dashboard specification: Pydantic models, encoding rules and auto-layout.

Panels store SQL, never data. The web app re-runs each panel's SQL on every render.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PanelType = Literal["kpi", "line", "area", "bar", "stacked_bar", "horizontal_bar", "donut", "table", "scatter", "heatmap"]
PANEL_TYPES: tuple[str, ...] = PanelType.__args__  # type: ignore[attr-defined]
ValueFormat = Literal["number", "decimal", "currency", "usd", "percent", "minutes", "ms"]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
GRID_COLUMNS = 12

# Which encoding fields each panel type needs, and what they mean.
REQUIRED_ENCODING: dict[str, tuple[str, ...]] = {
    "kpi": ("value",),
    "line": ("x", "y"),
    "area": ("x", "y"),
    "bar": ("x", "y"),
    "stacked_bar": ("x", "y", "series"),
    "horizontal_bar": ("x", "y"),
    "donut": ("label", "value"),
    "table": (),
    "scatter": ("x", "y"),
    "heatmap": ("x", "y", "value"),
}

ENCODING_HELP: dict[str, str] = {
    "kpi": "value = numeric column. Optional x = period column: rows ordered by x give the sparkline, "
           "the last row is the headline and the change is measured against the previous row.",
    "line": "x = time/category column, y = numeric column. Optional series = column that splits lines.",
    "area": "x = time column, y = numeric column. Optional series = column that splits areas.",
    "bar": "x = category column, y = numeric column. Optional series = grouped bars.",
    "stacked_bar": "x = category/time column, y = numeric column, series = column whose values are stacked.",
    "horizontal_bar": "x = category column (shown on the vertical axis), y = numeric column (bar length).",
    "donut": "label = category column, value = numeric column. Keep to ≤ 6 slices.",
    "table": "No encoding required; all columns are shown. Optional format applies to numeric columns.",
    "scatter": "x = numeric column, y = numeric column. Optional label = point label column, series = colour groups.",
    "heatmap": "x = column for heatmap columns, y = column for heatmap rows, value = numeric cell value.",
}

DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "kpi": (3, 2),
    "line": (6, 4),
    "area": (6, 4),
    "bar": (6, 4),
    "stacked_bar": (6, 4),
    "horizontal_bar": (6, 4),
    "donut": (4, 4),
    "table": (6, 4),
    "scatter": (6, 4),
    "heatmap": (12, 4),
}


class Encoding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: str | None = Field(None, description="Column for the x axis / categories / time.")
    y: str | None = Field(None, description="Numeric column for the y axis (bar length for horizontal_bar).")
    series: str | None = Field(None, description="Column whose distinct values become separate series.")
    value: str | None = Field(None, description="Numeric column for kpi, donut and heatmap cells.")
    label: str | None = Field(None, description="Category column for donut slices or scatter point labels.")
    format: ValueFormat | None = Field(None, description="How to display numbers: number, decimal, currency (INR), "
                                                         "usd, percent (values are 0-1 fractions), minutes, ms.")


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Slug, unique within the dashboard, e.g. 'revenue-trend'.")
    type: PanelType
    title: str = Field(..., min_length=1, max_length=90)
    sql: str = Field(..., min_length=1, description="One read-only SELECT. Re-run on every render.")
    encoding: Encoding = Field(default_factory=Encoding)
    insight: str = Field("", max_length=240, description="One sentence: what the reader should notice.")

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("panel id must be a lowercase slug: letters, digits and '-', e.g. 'refunds-by-reason'")
        return v


class LayoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_id: str
    x: int = Field(..., ge=0, le=GRID_COLUMNS - 1, description="Column 0-11 on a 12-column grid.")
    y: int = Field(..., ge=0, le=200, description="Row (grid units, top = 0).")
    w: int = Field(..., ge=1, le=GRID_COLUMNS, description="Width in columns (KPI 3, chart 6, full width 12).")
    h: int = Field(..., ge=1, le=12, description="Height in grid rows (~80 px each; KPI 2, chart 4).")


class DashboardSpec(BaseModel):
    """A dashboard: an ordered set of SQL-backed panels on a 12-column grid."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Slug for the dashboard, e.g. 'coo-weekly'.")
    title: str = Field(..., min_length=1, max_length=90)
    subtitle: str = Field("", max_length=200)
    layout: list[LayoutItem] = Field(default_factory=list,
                                     description="Optional. Panels without a layout entry are auto-placed in order.")
    panels: list[Panel] = Field(..., min_length=1, max_length=12)
    refresh_seconds: int = Field(30, ge=10, le=3600)
    version: int = Field(0, description="Set by the server.")
    updated_at: str | None = Field(None, description="Set by the server.")

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("dashboard id must be a lowercase slug: letters, digits and '-', e.g. 'coo-overview'")
        return v


class PanelPatch(BaseModel):
    """Partial panel update; omitted fields keep their current value. Encoding keys are merged."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: PanelType | None = None
    title: str | None = Field(None, min_length=1, max_length=90)
    sql: str | None = None
    encoding: Encoding | None = None
    insight: str | None = Field(None, max_length=240)


class DashboardPatch(BaseModel):
    """Changes to apply to an existing dashboard. Every field is optional."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, min_length=1, max_length=90)
    subtitle: str | None = Field(None, max_length=200)
    refresh_seconds: int | None = Field(None, ge=10, le=3600)
    panels: list[PanelPatch] = Field(default_factory=list,
                                     description="Panels to update (matched by id) or add (new id: give type, title, sql).")
    remove_panel_ids: list[str] = Field(default_factory=list)
    layout: list[LayoutItem] = Field(default_factory=list,
                                     description="Layout entries to set/replace, matched by panel_id.")
    panel_order: list[str] | None = Field(None, description="Optional new order of panel ids; layout is re-flowed.")


# --------------------------------------------------------------------------- layout


def auto_layout(spec: DashboardSpec) -> DashboardSpec:
    """Keep valid layout entries; place every other panel after them, flowing left to right."""
    ids = [p.id for p in spec.panels]
    kept = [item for item in spec.layout if item.panel_id in ids]
    seen: set[str] = set()
    unique: list[LayoutItem] = []
    for item in kept:
        if item.panel_id not in seen:
            w = min(item.w, GRID_COLUMNS - item.x)
            unique.append(item.model_copy(update={"w": w}))
            seen.add(item.panel_id)
    cursor_y = max((i.y + i.h for i in unique), default=0)
    cursor_x, row_h = 0, 0
    for p in spec.panels:
        if p.id in seen:
            continue
        w, h = DEFAULT_SIZE[p.type]
        if cursor_x + w > GRID_COLUMNS:
            cursor_x, cursor_y, row_h = 0, cursor_y + row_h, 0
        unique.append(LayoutItem(panel_id=p.id, x=cursor_x, y=cursor_y, w=w, h=h))
        cursor_x += w
        row_h = max(row_h, h)
    order = {pid: i for i, pid in enumerate(ids)}
    unique.sort(key=lambda i: (i.y, i.x, order[i.panel_id]))
    return spec.model_copy(update={"layout": unique})


def reflow(spec: DashboardSpec) -> DashboardSpec:
    """Discard positions and re-place all panels in panel order."""
    return auto_layout(spec.model_copy(update={"layout": []}))
