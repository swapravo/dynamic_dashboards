"""Run and check every panel of a dashboard spec, producing actionable errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config, sqlguard
from .spec import ENCODING_HELP, REQUIRED_ENCODING, DashboardSpec, LayoutItem, Panel, auto_layout, reflow

NUMERIC_FIELDS = ("y", "value")
MAX_RECOMMENDED_PANELS = 8


class SpecError(ValueError):
    """The spec cannot be saved. `errors` lists every problem found."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(format_errors(errors))


def format_errors(errors: list[str]) -> str:
    lines = [f"Dashboard spec has {len(errors)} problem(s). Fix them and call the tool again:"]
    lines += [f"  {i}. {e}" for i, e in enumerate(errors, 1)]
    return "\n".join(lines)


@dataclass
class PanelRun:
    panel_id: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"panel_id": self.panel_id, "columns": self.columns, "rows": self.rows, "row_count": self.row_count,
                "truncated": self.truncated, "elapsed_ms": round(self.elapsed_ms, 1), "error": self.error}


def run_panel(panel: Panel) -> PanelRun:
    try:
        res = sqlguard.run_select(panel.sql, limit=config.MAX_PANEL_ROWS)
    except sqlguard.QueryError as err:
        return PanelRun(panel.id, error=str(err))
    return PanelRun(panel.id, res.columns, res.rows, res.row_count, res.truncated, res.elapsed_ms)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_panel(panel: Panel, run: PanelRun) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    where = f"panel '{panel.id}' ({panel.type})"
    if run.error:
        errors.append(f"{where}: SQL failed: {run.error}")
        return errors, warnings
    if run.truncated:
        errors.append(f"{where}: SQL returns more than {config.MAX_PANEL_ROWS} rows. Aggregate (GROUP BY) or add "
                      "a LIMIT so the panel shows a readable amount of data.")
    cols = run.columns
    enc = panel.encoding.model_dump()
    for name in REQUIRED_ENCODING[panel.type]:
        if not enc.get(name):
            errors.append(f"{where}: encoding.{name} is required. {ENCODING_HELP[panel.type]} "
                          f"Result columns: {', '.join(cols)}.")
    for name in ("x", "y", "series", "value", "label"):
        col = enc.get(name)
        if col and col not in cols:
            errors.append(f"{where}: encoding.{name} = '{col}' is not a column of the SQL result. "
                          f"Result columns: {', '.join(cols)}. Use one of these or alias the column in SQL.")
    if errors:
        return errors, warnings
    if run.row_count == 0:
        warnings.append(f"{where}: SQL returned 0 rows; the panel will be empty. Check date filters.")
        return errors, warnings
    if panel.type == "scatter":
        numeric = ("x", "y")
    elif panel.type == "kpi":
        numeric = ("value",)
    else:
        numeric = NUMERIC_FIELDS
    for name in numeric:
        col = enc.get(name)
        if not col:
            continue
        idx = cols.index(col)
        sample = [r[idx] for r in run.rows[:200] if r[idx] is not None]
        if sample and not all(_is_number(v) for v in sample):
            errors.append(f"{where}: encoding.{name} = '{col}' must be numeric but contains text "
                          f"(e.g. {str(next(v for v in sample if not _is_number(v)))[:40]!r}). "
                          "CAST it in SQL or choose another column.")
    if panel.type == "donut":
        if run.row_count > 8:
            warnings.append(f"{where}: {run.row_count} slices; donuts read best with ≤ 6. Consider horizontal_bar.")
    if panel.type in ("line", "area") and run.row_count == 1:
        warnings.append(f"{where}: only 1 row; a line needs several points. Consider kpi or bar.")
    if not panel.insight.strip():
        warnings.append(f"{where}: add a one-line insight telling the reader what to notice.")
    return errors, warnings


def _overlaps(items: list[LayoutItem]) -> bool:
    cells: set[tuple[int, int]] = set()
    for it in items:
        for x in range(it.x, it.x + it.w):
            for y in range(it.y, it.y + it.h):
                if (x, y) in cells:
                    return True
                cells.add((x, y))
    return False


def validate_spec(spec: DashboardSpec) -> tuple[DashboardSpec, list[PanelRun], list[str]]:
    """Return (spec with complete layout, panel runs, warnings) or raise SpecError with every problem."""
    errors: list[str] = []
    warnings: list[str] = []
    ids = [p.id for p in spec.panels]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"duplicate panel ids: {', '.join(dupes)}. Each panel needs a unique id.")
    unknown = [it.panel_id for it in spec.layout if it.panel_id not in ids]
    if unknown:
        warnings.append(f"layout entries for unknown panels were ignored: {', '.join(unknown)}.")
    for it in spec.layout:
        if it.x + it.w > 12:
            warnings.append(f"layout for '{it.panel_id}' overflowed the 12-column grid and was narrowed.")
    if len(spec.panels) > MAX_RECOMMENDED_PANELS:
        warnings.append(f"{len(spec.panels)} panels; the design guide recommends at most {MAX_RECOMMENDED_PANELS}.")

    runs: list[PanelRun] = []
    for panel in spec.panels:
        run = run_panel(panel)
        runs.append(run)
        e, w = check_panel(panel, run)
        errors += e
        warnings += w
    if errors:
        raise SpecError(errors)

    laid_out = auto_layout(spec)
    if _overlaps(laid_out.layout):
        warnings.append("layout entries overlapped, so all panels were re-flowed in panel order.")
        laid_out = reflow(spec)
    return laid_out, runs, warnings
