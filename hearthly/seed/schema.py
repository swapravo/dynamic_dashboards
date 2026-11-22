"""DDL for the Hearthly business database (data/hearthly.db)."""

from __future__ import annotations

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    email               TEXT NOT NULL,
    city                TEXT NOT NULL,
    state               TEXT NOT NULL,
    region              TEXT NOT NULL,
    segment             TEXT NOT NULL CHECK (segment IN ('new', 'returning', 'vip')),
    signup_date         TEXT NOT NULL,
    acquisition_channel TEXT NOT NULL
);

CREATE TABLE products (
    id         INTEGER PRIMARY KEY,
    sku        TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    unit_cost  REAL NOT NULL,
    list_price REAL NOT NULL
);

CREATE TABLE campaigns (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    spend      REAL NOT NULL
);

CREATE TABLE orders (
    id              INTEGER PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    order_date      TEXT NOT NULL,
    status          TEXT NOT NULL,
    channel         TEXT NOT NULL,
    campaign_id     INTEGER REFERENCES campaigns(id),
    discount_amount REAL NOT NULL,
    shipping_fee    REAL NOT NULL,
    payment_method  TEXT NOT NULL
);

CREATE TABLE order_items (
    id         INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    batch_code TEXT NOT NULL
);

CREATE TABLE shipments (
    id                INTEGER PRIMARY KEY,
    order_id          INTEGER NOT NULL REFERENCES orders(id),
    courier           TEXT NOT NULL,
    dispatched_at     TEXT NOT NULL,
    promised_date     TEXT NOT NULL,
    delivered_at      TEXT,
    status            TEXT NOT NULL,
    destination_state TEXT
);

CREATE TABLE refunds (
    id            INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(id),
    order_item_id INTEGER REFERENCES order_items(id),
    requested_at  TEXT NOT NULL,
    resolved_at   TEXT,
    amount        REAL NOT NULL,
    reason        TEXT NOT NULL,
    resolution    TEXT NOT NULL,
    handled_by    TEXT NOT NULL CHECK (handled_by IN ('human', 'refunddesk_agent'))
);

CREATE TABLE support_tickets (
    id                     INTEGER PRIMARY KEY,
    customer_id            INTEGER NOT NULL REFERENCES customers(id),
    order_id               INTEGER REFERENCES orders(id),
    created_at             TEXT NOT NULL,
    category               TEXT NOT NULL,
    channel                TEXT NOT NULL,
    first_response_minutes INTEGER NOT NULL,
    resolved_at            TEXT,
    csat                   INTEGER
);

CREATE TABLE agent_runs (
    id                 INTEGER PRIMARY KEY,
    ticket_id          INTEGER REFERENCES support_tickets(id),
    refund_id          INTEGER REFERENCES refunds(id),
    run_at             TEXT NOT NULL,
    agent_version      TEXT NOT NULL,
    model              TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    latency_ms         INTEGER NOT NULL,
    tokens_in          INTEGER NOT NULL,
    tokens_out         INTEGER NOT NULL,
    cost_usd           REAL NOT NULL,
    decision           TEXT NOT NULL,
    audit_correct      INTEGER,
    escalated_to_human INTEGER NOT NULL,
    steps              INTEGER NOT NULL
);

CREATE INDEX idx_customers_state       ON customers(state);
CREATE INDEX idx_customers_signup      ON customers(signup_date);
CREATE INDEX idx_orders_date           ON orders(order_date);
CREATE INDEX idx_orders_customer       ON orders(customer_id);
CREATE INDEX idx_orders_campaign       ON orders(campaign_id);
CREATE INDEX idx_items_order           ON order_items(order_id);
CREATE INDEX idx_items_product         ON order_items(product_id);
CREATE INDEX idx_items_batch           ON order_items(batch_code);
CREATE INDEX idx_shipments_order       ON shipments(order_id);
CREATE INDEX idx_shipments_courier     ON shipments(courier, dispatched_at);
CREATE INDEX idx_shipments_dest        ON shipments(destination_state);
CREATE INDEX idx_refunds_order         ON refunds(order_id);
CREATE INDEX idx_refunds_item          ON refunds(order_item_id);
CREATE INDEX idx_refunds_requested     ON refunds(requested_at);
CREATE INDEX idx_tickets_created       ON support_tickets(created_at);
CREATE INDEX idx_tickets_order         ON support_tickets(order_id);
CREATE INDEX idx_tickets_customer      ON support_tickets(customer_id);
CREATE INDEX idx_agent_runs_run_at     ON agent_runs(run_at);
CREATE INDEX idx_agent_runs_prompt     ON agent_runs(prompt_version);
CREATE INDEX idx_agent_runs_ticket     ON agent_runs(ticket_id);
CREATE INDEX idx_agent_runs_refund     ON agent_runs(refund_id);
"""

TABLE_ORDER = [
    "customers",
    "products",
    "campaigns",
    "orders",
    "order_items",
    "shipments",
    "refunds",
    "support_tickets",
    "agent_runs",
]
