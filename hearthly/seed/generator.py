"""Deterministic synthetic data generator for Hearthly.

Everything flows from one `random.Random(seed)` and a fixed iteration order, so the same
seed and the same `as_of` date produce identical tables. No dict/set iteration over hashed
strings is used for ordering decisions.
"""

from __future__ import annotations

import bisect
import itertools
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Sequence, TypeVar

from . import catalog
from .timeline import (
    AGENT_LAUNCH_AGO,
    COURIER_DELAY_START_AGO,
    KETTLE_BATCH_DAYS,
    KETTLE_BATCH_START_AGO,
    MODEL_SWAP_AGO,
    PROMPT_V2_AGO,
    PROMPT_V3_AGO,
    PROMPT_V4_AGO,
    Timeline,
    seasonal_factor,
    WEEKDAY_FACTOR,
)

T = TypeVar("T")

N_BASE_CUSTOMERS = 54_000
FLASH_LIFT = 0.36  # extra deal-seeker first orders per flash-day order
RETURN_WINDOW_DAYS = 30

# name, channel, (month, day) start, (month, day) end, attribution probability, daily spend
SEASONAL_CAMPAIGNS: tuple[tuple[str, str, tuple[int, int], tuple[int, int], float, float], ...] = (
    ("Diwali Festive Edit", "paid_social", (10, 1), (11, 12), 0.34, 52_000),
    ("January Home Refresh Sale", "email", (1, 1), (1, 20), 0.33, 38_000),
    ("Wedding Season Gifting", "influencer", (2, 1), (3, 10), 0.18, 21_000),
    ("Monsoon Kitchen Upgrade", "search_ads", (7, 1), (8, 15), 0.16, 18_000),
)
ALWAYS_ON_CAMPAIGNS: tuple[tuple[str, str, float, float], ...] = (
    ("Search Always-On", "search_ads", 0.07, 9_000),
    ("Instagram Creators Program", "paid_social", 0.05, 7_500),
)
FLASH_CAMPAIGN = ("Weekend Flash Sale", "paid_social", 0.90, 65_000)  # spend per flash day

PROMPT_ACCURACY = {  # prompt_version -> (boundary_case_accuracy, normal_case_accuracy)
    "v1": (0.80, 0.89),
    "v2": (0.85, 0.92),
    "v3": (0.87, 0.94),
    "v4": (0.50, 0.91),
}
MODEL_PRO = "hx-pro-2026-03"
MODEL_LITE = "hx-lite-2026-10"


# --------------------------------------------------------------------------- helpers


def _cum(weights: Sequence[float]) -> list[float]:
    return list(itertools.accumulate(weights))


def _pick(rng: random.Random, items: Sequence[T], cum: Sequence[float]) -> T:
    return items[bisect.bisect_right(cum, rng.random() * cum[-1])]


def _ts(d: date, rng: random.Random, lo_hour: int = 8, hi_hour: int = 22) -> datetime:
    return datetime(d.year, d.month, d.day, rng.randint(lo_hour, hi_hour - 1), rng.randint(0, 59), rng.randint(0, 59))


def _fmt(t: datetime | None) -> str | None:
    return None if t is None else t.strftime("%Y-%m-%d %H:%M:%S")


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return median * math.exp(rng.gauss(0, sigma))


@dataclass
class Customer:
    gen_idx: int
    name: str
    city: str
    state: str
    region: str
    signup: date
    channel: str
    order_dates: list[date] = field(default_factory=list)
    deal_seeker: bool = False
    id: int = 0


@dataclass
class Order:
    customer: Customer
    order_date: date
    first_for_customer: bool
    deal_seeker_first: bool
    id: int = 0


@dataclass
class Dataset:
    """Rows ready for insertion, keyed by table name."""

    rows: dict[str, list[tuple[Any, ...]]]
    timeline: Timeline


# --------------------------------------------------------------------------- generator


class HearthlyGenerator:
    def __init__(self, as_of: date, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.tl = Timeline(as_of)
        self.days = self.tl.days()
        self.flash_start, self.flash_end = self.tl.flash_window()
        self.state_cum = _cum([s.weight for s in catalog.STATES])
        self.acq_items = [c for c, _ in catalog.ACQUISITION_CHANNELS]
        self.acq_cum = _cum([w for _, w in catalog.ACQUISITION_CHANNELS])
        self.max_season = max(WEEKDAY_FACTOR) * 1.55

    # ----- customers & order timing

    def _is_flash_day(self, d: date) -> bool:
        return self.flash_start <= d <= self.flash_end and d.weekday() >= 5

    def _new_customer(self, idx: int, signup: date, deal_seeker: bool = False) -> Customer:
        rng = self.rng
        st = _pick(rng, catalog.STATES, self.state_cum)
        first, last = rng.choice(catalog.FIRST_NAMES), rng.choice(catalog.LAST_NAMES)
        channel = "paid_social" if deal_seeker and rng.random() < 0.8 else _pick(rng, self.acq_items, self.acq_cum)
        return Customer(idx, f"{first} {last}", rng.choice(st.cities), st.name, st.region, signup, channel, deal_seeker=deal_seeker)

    def _order_process(self, c: Customer, p_stop: float, mean_gap: float) -> None:
        """First order on signup, then repeat orders with exponential gaps thinned by seasonality."""
        rng, tl = self.rng, self.tl
        d = c.signup
        dates = [d]
        while rng.random() > p_stop:
            # walk forward until a seasonality-thinned day is accepted
            while True:
                d = d + timedelta(days=max(2, int(rng.expovariate(1 / mean_gap))))
                if d > tl.end:
                    break
                accept = WEEKDAY_FACTOR[d.weekday()] * seasonal_factor(d) / self.max_season
                if rng.random() < accept:
                    break
            if d > tl.end:
                break
            dates.append(d)
        c.order_dates = [x for x in dates if tl.start <= x <= tl.end]

    def _customers(self) -> list[Customer]:
        rng, tl = self.rng, self.tl
        in_window_cum = _cum([tl.day_weight(d) for d in self.days])
        customers: list[Customer] = []
        for i in range(N_BASE_CUSTOMERS):
            if rng.random() < 0.40:  # signed up before the 18-month window
                signup = tl.start - timedelta(days=rng.randint(1, 540))
            else:
                signup = _pick(rng, self.days, in_window_cum)
            c = self._new_customer(i, signup)
            kind = rng.random()
            if kind < 0.42:
                self._order_process(c, p_stop=0.72, mean_gap=110)
            elif kind < 0.86:
                self._order_process(c, p_stop=0.21, mean_gap=40)
            else:
                self._order_process(c, p_stop=0.07, mean_gap=21)
            customers.append(c)

        # Weekend Flash Sale: deal-seekers arrive on flash days and rarely come back.
        per_day: dict[date, int] = {}
        for c in customers:
            for d in c.order_dates:
                if self._is_flash_day(d):
                    per_day[d] = per_day.get(d, 0) + 1
        idx = len(customers)
        for d in sorted(per_day):
            for _ in range(round(per_day[d] * FLASH_LIFT)):
                c = self._new_customer(idx, d, deal_seeker=True)
                self._order_process(c, p_stop=0.90, mean_gap=95)
                customers.append(c)
                idx += 1

        kept = [c for c in customers if c.order_dates]
        kept.sort(key=lambda c: (c.signup, c.gen_idx))
        for new_id, c in enumerate(kept, start=1):
            c.id = new_id
        return kept

    # ----- main build

    def build(self) -> Dataset:
        rng, tl = self.rng, self.tl
        customers = self._customers()

        orders: list[Order] = []
        for c in customers:
            for k, d in enumerate(c.order_dates):
                first = k == 0 and c.signup >= tl.start
                orders.append(Order(c, d, first, first and c.deal_seeker))
        orders.sort(key=lambda o: (o.order_date, o.customer.id))
        for i, o in enumerate(orders, start=1):
            o.id = i

        rows: dict[str, list[tuple[Any, ...]]] = {t: [] for t in (
            "customers", "products", "campaigns", "orders", "order_items", "shipments",
            "refunds", "support_tickets", "agent_runs")}

        # products
        products = catalog.PRODUCTS
        for pid, p in enumerate(products, start=1):
            rows["products"].append((pid, p.sku, p.name, p.category, p.unit_cost, p.list_price))
        prod_cum_normal = _cum([p.weight for p in products])
        prod_cum_festive = _cum([p.weight * catalog.FESTIVE_CATEGORY_BOOST.get(p.category, 1.0) for p in products])
        kettle_pid = next(i for i, p in enumerate(products, start=1) if p.sku == "KA-KETTLE")
        product_ids = list(range(1, len(products) + 1))

        # campaigns
        campaign_windows = self._campaigns(rows["campaigns"])
        flash_campaign_id = next(r[0] for r in rows["campaigns"] if r[1] == FLASH_CAMPAIGN[0])

        # segments from order counts
        counts: dict[int, int] = {}
        for o in orders:
            counts[o.customer.id] = counts.get(o.customer.id, 0) + 1
        for c in customers:
            n = counts[c.id]
            segment = "new" if n == 1 else ("vip" if n >= 6 else "returning")
            email = f"{c.name.split()[0].lower()}.{c.name.split()[1].lower().replace(chr(39), '')}{c.id}@example.com"
            rows["customers"].append((c.id, c.name, email, c.city, c.state, c.region, segment, c.signup.isoformat(), c.channel))

        ch_items = [x for x, _ in catalog.ORDER_CHANNELS]
        ch_cum = _cum([w for _, w in catalog.ORDER_CHANNELS])
        pay_items = [x for x, _ in catalog.PAYMENT_METHODS]
        pay_cum = _cum([w for _, w in catalog.PAYMENT_METHODS])
        courier_items = [x for x, _ in catalog.COURIERS]
        courier_cum = _cum([w for _, w in catalog.COURIERS])
        courier_cum_ne = _cum([w * (1.6 if x == "SwiftShip" else 1.0) for x, w in catalog.COURIERS])
        reason_items = [x for x, _ in catalog.REFUND_REASONS]
        reason_cum = _cum([w for _, w in catalog.REFUND_REASONS])

        kettle_b17_start = tl.ago(KETTLE_BATCH_START_AGO)
        kettle_b17_end = kettle_b17_start + timedelta(days=KETTLE_BATCH_DAYS - 1)
        courier_delay_start = tl.ago(COURIER_DELAY_START_AGO)

        item_id = 0
        shipment_id = 0
        refund_requests: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []

        for o in orders:
            c = o.customer
            d = o.order_date
            channel = _pick(rng, ch_items, ch_cum)
            payment = _pick(rng, pay_items, pay_cum)

            # campaign attribution
            campaign_id: int | None = None
            discount_rate = 0.0
            if self._is_flash_day(d) and (o.deal_seeker_first or rng.random() < FLASH_CAMPAIGN[2]):
                campaign_id = flash_campaign_id
                discount_rate = rng.uniform(0.10, 0.13)
            else:
                for cid, start, end, prob in campaign_windows:
                    if cid != flash_campaign_id and start <= d <= end and rng.random() < prob:
                        campaign_id = cid
                        discount_rate = rng.uniform(0.07, 0.11)
                        break
                if campaign_id is None and rng.random() < 0.22:
                    discount_rate = 0.05

            # items
            n_items = _pick(rng, (1, 2, 3, 4), (0.55, 0.85, 0.97, 1.0))
            cum = prod_cum_festive if d.month in (10, 11) else prod_cum_normal
            chosen: list[int] = []
            while len(chosen) < n_items:
                pid = _pick(rng, product_ids, cum)
                if pid not in chosen:
                    chosen.append(pid)

            cancelled = rng.random() < 0.025
            dispatch_day = d + timedelta(days=_pick(rng, (0, 1, 2), (0.45, 0.90, 1.0)))
            items: list[tuple[int, int, int, float]] = []  # item_id, product_id, qty, unit_price
            subtotal = 0.0
            for pid in chosen:
                item_id += 1
                p = products[pid - 1]
                qty = _pick(rng, (1, 2, 3), (0.88, 0.98, 1.0))
                price = p.list_price
                if pid == kettle_pid:
                    batch = tl.kettle_batch(dispatch_day)
                else:
                    batch = f"{p.sku.split('-')[0]}-{(dispatch_day.year % 100):02d}{dispatch_day.month:02d}-{1 + (dispatch_day.day - 1) // 10}"
                rows["order_items"].append((item_id, o.id, pid, qty, price, batch))
                items.append((item_id, pid, qty, price))
                subtotal += qty * price
            discount = round(subtotal * discount_rate, 2)
            shipping_fee = 0.0 if subtotal >= 999 else 79.0

            if cancelled:
                rows["orders"].append((o.id, c.id, d.isoformat(), "cancelled", channel, campaign_id, discount, shipping_fee, payment))
                continue

            # shipment
            shipment_id += 1
            ne = c.region == "Northeast"
            courier = _pick(rng, courier_items, courier_cum_ne if ne else courier_cum)
            dispatched_at = _ts(dispatch_day, rng, 9, 20)
            sla = 6 if ne else (4 if c.region in ("East", "Central") else 3)
            promised = dispatch_day + timedelta(days=sla)
            story_delay = courier == "SwiftShip" and ne and dispatch_day >= courier_delay_start
            late = rng.random() < (0.37 if story_delay else 0.058)
            if late:
                deliver_day = promised + timedelta(days=rng.randint(2, 7) if story_delay else rng.randint(1, 4))
            else:
                deliver_day = dispatch_day + timedelta(days=rng.randint(1, sla))
            delivered_at: datetime | None = _ts(deliver_day, rng, 9, 21)
            if deliver_day > tl.end:
                delivered_at = None
            status = "delivered" if delivered_at else "in_transit"
            dest_state: str | None = None if rng.random() < 0.01 else c.state
            rows["shipments"].append((shipment_id, o.id, courier, _fmt(dispatched_at), promised.isoformat(),
                                      _fmt(delivered_at), status, dest_state))
            rows["orders"].append((o.id, c.id, d.isoformat(), status, channel, campaign_id, discount, shipping_fee, payment))

            # support: where-is-my-order
            if late and rng.random() < 0.55:
                tickets.append(self._ticket(c.id, o.id, promised + timedelta(days=rng.randint(1, 2)), "where_is_my_order", late=True))
            elif rng.random() < 0.022:
                tickets.append(self._ticket(c.id, o.id, dispatch_day + timedelta(days=rng.randint(2, 4)), "where_is_my_order"))
            if rng.random() < 0.006:
                tickets.append(self._ticket(c.id, o.id, d, "payment_issue"))
            if rng.random() < 0.005:
                tickets.append(self._ticket(c.id, None, d + timedelta(days=rng.randint(0, 20)), "account"))

            if delivered_at is None:
                continue

            # refund requests and product issues, per item
            for iid, pid, qty, price in items:
                p_ref = 0.030
                reason_override: str | None = None
                is_b17 = pid == kettle_pid and kettle_b17_start <= dispatch_day <= kettle_b17_end
                if is_b17:
                    p_ref = 0.105
                    if rng.random() < 0.80:
                        reason_override = "defective"
                if late and rng.random() < 0.04:
                    p_ref, reason_override = 1.0, "late_delivery"
                if rng.random() >= p_ref:
                    if rng.random() < 0.010:
                        tickets.append(self._ticket(c.id, o.id, deliver_day + timedelta(days=rng.randint(1, 10)), "product_issue"))
                    continue
                reason = reason_override or _pick(rng, reason_items, reason_cum)
                late_arriving = rng.random() < 0.004
                if late_arriving:
                    req_day = d + timedelta(days=rng.randint(90, 150))
                else:
                    u = rng.random()
                    if u < 0.68:
                        delay = min(26, int(rng.expovariate(1 / 7)))
                    elif u < 0.92:
                        delay = rng.randint(27, 33)
                    else:
                        delay = rng.randint(34, 60)
                    req_day = deliver_day + timedelta(days=delay)
                if req_day > tl.end:
                    continue
                refund_requests.append({
                    "order_id": o.id, "item_id": iid, "customer_id": c.id, "req_day": req_day,
                    "days_after_delivery": (req_day - deliver_day).days, "amount": round(qty * price, 2),
                    "reason": reason, "late_arriving": late_arriving,
                })

        self._refunds_and_agent(rows, refund_requests, tickets)
        return Dataset(rows, tl)

    # ----- campaigns

    def _campaigns(self, out: list[tuple[Any, ...]]) -> list[tuple[int, date, date, float]]:
        tl = self.tl
        specs: list[tuple[str, str, date, date, float, float]] = []
        for name, ch, (sm, sd), (em, ed), prob, daily in SEASONAL_CAMPAIGNS:
            for year in range(tl.start.year, tl.end.year + 1):
                s, e = date(year, sm, sd), date(year, em, ed)
                if e < tl.start or s > tl.end:
                    continue
                s, e = max(s, tl.start), min(e, tl.end)
                specs.append((f"{name} {year}", ch, s, e, prob, daily * ((e - s).days + 1)))
        for name, ch, prob, daily in ALWAYS_ON_CAMPAIGNS:
            specs.append((name, ch, tl.start, tl.end, prob, daily * tl.n_days))
        flash_days = sum(1 for d in self.days if self._is_flash_day(d))
        specs.append((FLASH_CAMPAIGN[0], FLASH_CAMPAIGN[1], self.flash_start, self.flash_end, FLASH_CAMPAIGN[2],
                      FLASH_CAMPAIGN[3] * flash_days))
        specs.sort(key=lambda s: (s[2], s[0]))
        windows: list[tuple[int, date, date, float]] = []
        # seasonal campaigns win over always-on ones when both are active
        for cid, (name, ch, s, e, prob, spend) in enumerate(specs, start=1):
            out.append((cid, name, ch, s.isoformat(), e.isoformat(), round(spend, 2)))
            windows.append((cid, s, e, prob))
        always_on = {n for n, *_ in ALWAYS_ON_CAMPAIGNS}
        windows.sort(key=lambda w: (out[w[0] - 1][1] in always_on, w[1]))
        return windows

    # ----- support tickets

    def _ticket(self, customer_id: int, order_id: int | None, day: date, category: str, *, late: bool = False,
                created: datetime | None = None, denied: bool = False) -> dict[str, Any]:
        rng = self.rng
        ch_items = [x for x, _ in catalog.TICKET_CHANNELS]
        channel = _pick(rng, ch_items, _cum([w for _, w in catalog.TICKET_CHANNELS]))
        created = created or _ts(day, rng, 7, 23)
        busy = 1.35 if seasonal_factor(day) > 1.3 else 1.0
        frm = max(1, round(_lognormal(rng, catalog.FIRST_RESPONSE_MEDIAN[channel] * busy, 0.65)))
        resolve_hours = _lognormal(rng, 20 if category != "account" else 6, 0.9)
        resolved: datetime | None = created + timedelta(minutes=frm, hours=resolve_hours)
        csat: int | None
        if late or denied:
            csat = _pick(rng, (1, 2, 3, 4, 5), (0.17, 0.38, 0.62, 0.85, 1.0))
        else:
            csat = _pick(rng, (1, 2, 3, 4, 5), (0.04, 0.10, 0.23, 0.53, 1.0))
        if rng.random() < 0.42:
            csat = None
        if resolved is not None and resolved.date() > self.tl.end:
            resolved, csat = None, None
        return {"customer_id": customer_id, "order_id": order_id, "created": created, "category": category,
                "channel": channel, "frm": frm, "resolved": resolved, "csat": csat}

    # ----- refunds + RefundDesk agent

    def _prompt_version(self, d: date) -> str:
        tl = self.tl
        if d >= tl.ago(PROMPT_V4_AGO):
            return "v4"
        if d >= tl.ago(PROMPT_V3_AGO):
            return "v3"
        if d >= tl.ago(PROMPT_V2_AGO):
            return "v2"
        return "v1"

    def _refunds_and_agent(self, rows: dict[str, list[tuple[Any, ...]]], requests: list[dict[str, Any]],
                           tickets: list[dict[str, Any]]) -> None:
        rng, tl = self.rng, self.tl
        agent_launch = tl.ago(AGENT_LAUNCH_AGO)
        model_swap = tl.ago(MODEL_SWAP_AGO)
        refunds: list[dict[str, Any]] = []
        runs: list[dict[str, Any]] = []

        for r in requests:
            requested = _ts(r["req_day"], rng, 7, 23)
            days_after = r["days_after_delivery"]
            if days_after <= RETURN_WINDOW_DAYS:
                correct = "partial" if r["reason"] == "changed_mind" and days_after > 14 else "approve"
            else:
                correct = "partial" if r["reason"] == "defective" else "deny"
            boundary = 27 <= days_after <= 33
            agent = r["req_day"] >= agent_launch and not r["late_arriving"] and rng.random() < 0.82
            via_ticket = rng.random() < 0.65
            decision = correct
            audit: int | None = None
            escalated = False
            run: dict[str, Any] | None = None
            if agent:
                escalated = rng.random() < (0.22 if r["amount"] > 3000 else 0.07)
                if escalated:
                    decision = "escalate"
                else:
                    pv = self._prompt_version(r["req_day"])
                    acc_b, acc_n = PROMPT_ACCURACY[pv]
                    ok = rng.random() < (acc_b if boundary else acc_n)
                    audit = 1 if ok else 0
                    if not ok:
                        decision = {"approve": "deny", "deny": "approve", "partial": "approve"}[correct]
                run = self._agent_run(requested, decision, audit, escalated, model_swap)
            final = correct if (not agent or escalated) else decision
            pending = r["req_day"] >= tl.end - timedelta(days=1) and (not agent or escalated)
            if pending:
                resolution, amount, resolved = "pending", r["amount"], None
            else:
                resolution = {"approve": "refunded", "partial": "partial_refund", "deny": "denied"}[final]
                amount = {"refunded": r["amount"], "partial_refund": round(r["amount"] * 0.5, 2), "denied": 0.0}[resolution]
                if agent and not escalated:
                    resolved = requested + timedelta(minutes=rng.randint(2, 25))
                else:
                    resolved = requested + timedelta(hours=_lognormal(rng, 40, 0.6))
                if r["late_arriving"]:
                    resolved = requested + timedelta(days=rng.randint(3, 12))
                if resolved.date() > tl.end:
                    resolution, amount, resolved = "pending", r["amount"], None
            ticket = None
            if via_ticket:
                ticket = self._ticket(r["customer_id"], r["order_id"], r["req_day"], "refund_request",
                                      created=requested, denied=resolution == "denied")
                tickets.append(ticket)
            refunds.append({
                "order_id": r["order_id"], "item_id": r["item_id"], "requested": requested, "resolved": resolved,
                "amount": amount, "reason": r["reason"], "resolution": resolution,
                "handled_by": "refunddesk_agent" if agent else "human", "ticket": ticket, "run": run,
            })
            if run is not None:
                run["refund"] = refunds[-1]
                run["ticket"] = ticket
                runs.append(run)

        # tickets: chronological ids
        for i, t in enumerate(sorted(tickets, key=lambda t: (t["created"], t["customer_id"], t["category"])), start=1):
            t["id"] = i
        for t in sorted(tickets, key=lambda t: t["id"]):
            rows["support_tickets"].append((t["id"], t["customer_id"], t["order_id"], _fmt(t["created"]), t["category"],
                                            t["channel"], t["frm"], _fmt(t["resolved"]), t["csat"]))
        # refunds: chronological ids
        refunds.sort(key=lambda f: (f["requested"], f["order_id"], f["item_id"]))
        for i, f in enumerate(refunds, start=1):
            f["id"] = i
            rows["refunds"].append((i, f["order_id"], f["item_id"], _fmt(f["requested"]), _fmt(f["resolved"]),
                                    f["amount"], f["reason"], f["resolution"], f["handled_by"]))
        runs.sort(key=lambda r: (r["run_at"], r["refund"]["id"]))
        for i, r in enumerate(runs, start=1):
            rows["agent_runs"].append((i, r["ticket"]["id"] if r["ticket"] else None, r["refund"]["id"], _fmt(r["run_at"]),
                                       r["agent_version"], r["model"], r["prompt_version"], r["latency_ms"],
                                       r["tokens_in"], r["tokens_out"], r["cost_usd"], r["decision"], r["audit"],
                                       1 if r["escalated"] else 0, r["steps"]))

    def _agent_run(self, requested: datetime, decision: str, audit: int | None, escalated: bool,
                   model_swap: date) -> dict[str, Any]:
        rng = self.rng
        run_at = requested + timedelta(minutes=rng.randint(1, 12), seconds=rng.randint(0, 59))
        pv = self._prompt_version(requested.date())
        lite = requested.date() >= model_swap
        steps = rng.randint(4, 9) if lite else rng.randint(3, 7)
        tokens_in = max(1500, int(rng.gauss(5200 + 450 * steps, 900)))
        tokens_out = max(120, int(rng.gauss(420 + 30 * steps, 110)))
        if lite:
            latency = int(rng.gauss(4300 + 520 * steps, 700))
            cost = tokens_in * 0.8e-6 + tokens_out * 4e-6
        else:
            latency = int(rng.gauss(2600 + 380 * steps, 500))
            cost = tokens_in * 3e-6 + tokens_out * 15e-6
        version = {"v1": "1.0.0", "v2": "1.1.0", "v3": "1.2.0", "v4": "1.3.0"}[pv]
        if lite:
            version = "1.3.1"
        return {"run_at": run_at, "agent_version": f"refunddesk-{version}", "model": MODEL_LITE if lite else MODEL_PRO,
                "prompt_version": pv, "latency_ms": max(800, latency), "tokens_in": tokens_in, "tokens_out": tokens_out,
                "cost_usd": round(cost, 5), "decision": decision, "audit": audit, "escalated": escalated, "steps": steps}
