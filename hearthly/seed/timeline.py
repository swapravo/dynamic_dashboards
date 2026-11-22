"""Calendar for the synthetic dataset: 18 months of history ending yesterday."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

HISTORY_DAYS = 548  # ~18 months

# Planted-story anchors, in days before "today" (as_of). Presenter-only: see docs/DEMO_SECRETS.md.
KETTLE_BATCH_START_AGO = 60
KETTLE_BATCH_DAYS = 15
COURIER_DELAY_START_AGO = 40
AGENT_LAUNCH_AGO = 270
PROMPT_V2_AGO = 200
PROMPT_V3_AGO = 120
PROMPT_V4_AGO = 21
MODEL_SWAP_AGO = 10
FLASH_WINDOW_DAYS = 91

WEEKDAY_FACTOR = (0.93, 0.90, 0.92, 0.96, 1.03, 1.20, 1.16)  # Mon..Sun


def seasonal_factor(d: date) -> float:
    """Festive season (Oct-Nov, peaking around Diwali) and the January sale."""
    if d.month == 10:
        return 1.30 if d.day <= 20 else 1.55
    if d.month == 11:
        return 1.55 if d.day <= 12 else 1.20
    if d.month == 1:
        return 1.35 if d.day <= 15 else 1.12
    return 1.0


def is_festive_or_january(d: date) -> bool:
    return d.month in (10, 11, 1)


@dataclass(frozen=True)
class Timeline:
    as_of: date  # "today": the data ends the day before
    start: date = field(init=False)
    end: date = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "end", self.as_of - timedelta(days=1))
        object.__setattr__(self, "start", self.end - timedelta(days=HISTORY_DAYS - 1))

    def ago(self, days: int) -> date:
        return self.as_of - timedelta(days=days)

    @property
    def n_days(self) -> int:
        return (self.end - self.start).days + 1

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.n_days)]

    def day_weight(self, d: date) -> float:
        growth = 1.0 + 0.30 * (d - self.start).days / self.n_days
        return growth * WEEKDAY_FACTOR[d.weekday()] * seasonal_factor(d)

    def flash_window(self) -> tuple[date, date]:
        """A ~13-week window, at least 15 weeks back, that avoids festive and January months."""
        end_ago = 105
        while True:
            end = self.ago(end_ago)
            start = end - timedelta(days=FLASH_WINDOW_DAYS - 1)
            span = [start + timedelta(days=i) for i in range(FLASH_WINDOW_DAYS)]
            if start < self.start + timedelta(days=30):
                raise RuntimeError("could not place flash-sale window")
            if not any(is_festive_or_january(d) for d in span):
                return start, end
            end_ago += 7

    def is_flash_day(self, d: date) -> bool:
        start, end = self.flash_window()
        return start <= d <= end and d.weekday() >= 5

    def kettle_batch(self, dispatch: date) -> str:
        """Kettle batches run ~monthly, then B17 covers a 15-day window, then fortnightly."""
        b17_start = self.ago(KETTLE_BATCH_START_AGO)
        if dispatch >= b17_start:
            n = 17 + (dispatch - b17_start).days // KETTLE_BATCH_DAYS
        else:
            span = (b17_start - self.start).days
            n = 1 + int(16 * (dispatch - self.start).days / span)
        return f"KT-B{max(n, 1):02d}"
