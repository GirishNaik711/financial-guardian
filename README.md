# Financial Guardian

A comprehensive financial monitoring and alerting system for Indian markets.

## Features

- **Holdings Management**: Sync holdings from Kite and Groww
- **Market Context**: Track Nifty, sectors, macro indicators, and geopolitical events
- **Alerts**: Real-time keyword-based alerts via Slack
- **Briefings**: Morning briefings and end-of-day wrap-ups
- **Data Pipeline**: Aggregate data from multiple sources (StockInsights, Perplexity, NewsAPI, AMFI, NSE RSS)

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env`

3. Run the application:
   ```bash
   python main.py
   ```

## Project Structure

- `config/` - Configuration and settings
- `db/` - Database connections and migrations
- `holdings/` - Portfolio sync and management
- `data_pipeline/` - Data ingestion from various sources
- `market_context/` - Market analysis and context
- `alerts/` - Alert triggers and notifications
- `briefing/` - Report generation and formatting
- `slack/` - Slack integration
- `scheduler/` - Job scheduling
- `utils/` - Utility functions
- `tests/` - Test fixtures and tests

## Requirements

See `requirements.txt` for all dependencies.
