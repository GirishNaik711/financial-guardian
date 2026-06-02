-- ================================================
-- FINANCIAL GUARDIAN — COMPLETE POSTGRES SCHEMA
-- Apply with: psql -U guardian_user -d financial_guardian -h localhost -f db/schema.sql
-- Safe to re-run: uses IF NOT EXISTS throughout
-- ================================================

CREATE TABLE IF NOT EXISTS equity_holdings (
    id                  SERIAL PRIMARY KEY,
    ticker              VARCHAR(20)     NOT NULL,
    exchange            VARCHAR(10)     NOT NULL DEFAULT 'NSE',
    company_name        VARCHAR(200),
    quantity            DECIMAL(15,4)   NOT NULL,
    avg_buy_price       DECIMAL(15,4)   NOT NULL,
    current_price       DECIMAL(15,4),
    current_value       DECIMAL(15,2),
    absolute_pnl        DECIMAL(15,2),
    pct_pnl             DECIMAL(8,4),
    sector              VARCHAR(100),
    instrument_token    BIGINT,
    isin                VARCHAR(20),
    last_synced_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_equity_holdings_ticker ON equity_holdings(ticker);
CREATE INDEX IF NOT EXISTS idx_equity_holdings_active ON equity_holdings(is_active);

CREATE TABLE IF NOT EXISTS fund_holdings (
    id                  SERIAL PRIMARY KEY,
    fund_code           VARCHAR(50)     NOT NULL,
    fund_name           VARCHAR(300)    NOT NULL,
    isin                VARCHAR(20),
    fund_house          VARCHAR(200),
    fund_type           VARCHAR(20)     NOT NULL CHECK (fund_type IN ('active', 'index')),
    benchmark_index     VARCHAR(200),
    units_held          DECIMAL(15,4)   NOT NULL,
    purchase_nav        DECIMAL(15,4)   NOT NULL,
    current_nav         DECIMAL(15,4),
    current_value       DECIMAL(15,2),
    absolute_pnl        DECIMAL(15,2),
    pct_pnl             DECIMAL(8,4),
    expense_ratio       DECIMAL(6,4),
    fund_manager_name   VARCHAR(200),
    last_nav_date       DATE,
    last_synced_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fund_holdings_code ON fund_holdings(fund_code);
CREATE INDEX IF NOT EXISTS idx_fund_holdings_type ON fund_holdings(fund_type);

CREATE TABLE IF NOT EXISTS bond_holdings (
    id                  SERIAL PRIMARY KEY,
    issuer_name         VARCHAR(200)    NOT NULL,
    instrument_name     VARCHAR(300)    NOT NULL,
    isin                VARCHAR(20),
    face_value          DECIMAL(15,2)   NOT NULL,
    coupon_rate         DECIMAL(6,4),
    maturity_date       DATE,
    current_value       DECIMAL(15,2),
    quantity            INTEGER         NOT NULL DEFAULT 1,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS watchlist (
    id                  SERIAL PRIMARY KEY,
    item_type           VARCHAR(20)     NOT NULL CHECK (item_type IN ('stock', 'fund')),
    identifier          VARCHAR(100)    NOT NULL,
    display_name        VARCHAR(300),
    notes               TEXT,
    date_added          DATE,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    last_synced_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_watchlist_identifier ON watchlist(identifier, item_type);

CREATE TABLE IF NOT EXISTS nav_history (
    id                  SERIAL PRIMARY KEY,
    fund_code           VARCHAR(50)     NOT NULL,
    nav_date            DATE            NOT NULL,
    nav_value           DECIMAL(15,4)   NOT NULL,
    benchmark_value     DECIMAL(15,4),
    tracking_error      DECIMAL(8,6),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (fund_code, nav_date)
);
CREATE INDEX IF NOT EXISTS idx_nav_history_fund_date ON nav_history(fund_code, nav_date DESC);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id                  SERIAL PRIMARY KEY,
    ticker              VARCHAR(20)     NOT NULL,
    snapshot_date       DATE            NOT NULL,
    open_price          DECIMAL(15,4),
    high_price          DECIMAL(15,4),
    low_price           DECIMAL(15,4),
    close_price         DECIMAL(15,4),
    volume              BIGINT,
    delivery_pct        DECIMAL(6,4),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_price_snapshots_ticker_date ON price_snapshots(ticker, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS news_items (
    id                  SERIAL PRIMARY KEY,
    source              VARCHAR(100)    NOT NULL,
    source_url          TEXT,
    headline            TEXT            NOT NULL,
    summary             TEXT,
    full_text           TEXT,
    related_tickers     VARCHAR(20)[],
    related_fund_codes  VARCHAR(50)[],
    sentiment           VARCHAR(20)     CHECK (sentiment IN ('positive', 'negative', 'neutral', 'unknown')),
    is_urgent           BOOLEAN         NOT NULL DEFAULT FALSE,
    published_at        TIMESTAMPTZ,
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_news_items_tickers   ON news_items USING GIN(related_tickers);
CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_items_urgent    ON news_items(is_urgent) WHERE is_urgent = TRUE;

CREATE TABLE IF NOT EXISTS corporate_filings (
    id                  SERIAL PRIMARY KEY,
    filing_id           VARCHAR(100)    UNIQUE,
    ticker              VARCHAR(20),
    company_name        VARCHAR(200),
    exchange            VARCHAR(10),
    announcement_type   VARCHAR(100),
    summary_header      TEXT,
    summary_text        TEXT,
    sentiment           VARCHAR(20),
    source_url          TEXT,
    published_at        TIMESTAMPTZ,
    is_urgent           BOOLEAN         NOT NULL DEFAULT FALSE,
    fetched_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker    ON corporate_filings(ticker);
CREATE INDEX IF NOT EXISTS idx_filings_published ON corporate_filings(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_filings_urgent    ON corporate_filings(is_urgent) WHERE is_urgent = TRUE;

CREATE TABLE IF NOT EXISTS market_context (
    id                      SERIAL PRIMARY KEY,
    context_date            DATE            NOT NULL,
    context_time            TIME            NOT NULL,
    nifty_50_value          DECIMAL(10,2),
    nifty_50_change_pct     DECIMAL(8,4),
    sensex_value            DECIMAL(10,2),
    sensex_change_pct       DECIMAL(8,4),
    india_vix               DECIMAL(8,4),
    fii_net_flow_cr         DECIMAL(15,2),
    dii_net_flow_cr         DECIMAL(15,2),
    usd_inr                 DECIMAL(10,4),
    crude_oil_usd           DECIMAL(10,4),
    sp500_change_pct        DECIMAL(8,4),
    nasdaq_change_pct       DECIMAL(8,4),
    market_regime           VARCHAR(50),
    sector_performance      JSONB,
    geopolitical_summary    TEXT,
    raw_context_json        JSONB,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_market_context_date ON market_context(context_date DESC);

CREATE TABLE IF NOT EXISTS alerts (
    id                  SERIAL PRIMARY KEY,
    alert_type          VARCHAR(100)    NOT NULL,
    severity            VARCHAR(20)     NOT NULL CHECK (severity IN ('urgent', 'warning', 'info')),
    related_ticker      VARCHAR(20),
    related_fund_code   VARCHAR(50),
    title               TEXT            NOT NULL,
    message             TEXT            NOT NULL,
    source_url          TEXT,
    slack_message_ts    VARCHAR(50),
    slack_channel       VARCHAR(100),
    is_acknowledged     BOOLEAN         NOT NULL DEFAULT FALSE,
    acknowledged_at     TIMESTAMPTZ,
    fired_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alerts_fired   ON alerts(fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_unacked ON alerts(is_acknowledged) WHERE is_acknowledged = FALSE;
CREATE INDEX IF NOT EXISTS idx_alerts_ticker  ON alerts(related_ticker);

CREATE TABLE IF NOT EXISTS briefings (
    id                      SERIAL PRIMARY KEY,
    briefing_type           VARCHAR(20)     NOT NULL CHECK (briefing_type IN ('morning', 'eod')),
    briefing_date           DATE            NOT NULL,
    content_markdown        TEXT            NOT NULL,
    content_slack_blocks    JSONB,
    slack_message_ts        VARCHAR(50),
    portfolio_value         DECIMAL(15,2),
    portfolio_change_pct    DECIMAL(8,4),
    holdings_flagged        INTEGER         DEFAULT 0,
    generated_at            TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    sent_at                 TIMESTAMPTZ,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_briefings_date ON briefings(briefing_date DESC);
CREATE INDEX IF NOT EXISTS idx_briefings_type ON briefings(briefing_type);

CREATE TABLE IF NOT EXISTS job_logs (
    id                  SERIAL PRIMARY KEY,
    job_name            VARCHAR(100)    NOT NULL,
    status              VARCHAR(20)     NOT NULL CHECK (status IN ('started', 'completed', 'failed', 'skipped')),
    started_at          TIMESTAMPTZ     NOT NULL,
    completed_at        TIMESTAMPTZ,
    duration_seconds    DECIMAL(10,3),
    records_processed   INTEGER,
    error_message       TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_job_logs_name_started ON job_logs(job_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_logs_status       ON job_logs(status);