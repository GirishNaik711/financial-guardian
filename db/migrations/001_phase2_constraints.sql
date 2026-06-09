-- Phase 2 constraint additions
-- Run once after Phase 1 schema has been applied.
-- All statements use IF NOT EXISTS / DO NOTHING patterns — safe to re-run.

-- Unique constraint on equity ticker for ON CONFLICT upsert
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_equity_ticker'
    ) THEN
        ALTER TABLE equity_holdings
            ADD CONSTRAINT uq_equity_ticker UNIQUE (ticker);
    END IF;
END $$;

-- Unique constraint on fund code for ON CONFLICT upsert
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_fund_code'
    ) THEN
        ALTER TABLE fund_holdings
            ADD CONSTRAINT uq_fund_code UNIQUE (fund_code);
    END IF;
END $$;

-- Unique constraint on watchlist identifier for ON CONFLICT upsert
-- (schema.sql already defines idx_watchlist_identifier as a unique index;
--  this named constraint makes upsert intent explicit)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_watchlist_identifier'
    ) THEN
        ALTER TABLE watchlist
            ADD CONSTRAINT uq_watchlist_identifier UNIQUE (identifier);
    END IF;
END $$;