# Privacy Policy

**Last updated:** April 23, 2026

## What WikiMind collects

WikiMind is a personal knowledge tool. When you use the browser extension or web app, the following data is sent to your configured WikiMind server:

- **Page URLs** you choose to clip
- **Search queries** you submit through the Ask feature

## Where data is stored

All data is stored on the WikiMind server you connect to:

- **Self-hosted:** Your own machine. Data stays local in `~/.wikimind/`.
- **WikiMind Cloud (wikimind.fly.dev):** A Fly.io-hosted instance with a PostgreSQL database. Data is stored in the `ord` (Chicago) region.

The browser extension stores your gateway URL and recent clip history locally in `chrome.storage.local`. This data never leaves your browser.

## Third-party services

WikiMind uses LLM providers (Anthropic, OpenAI, or Google) to compile ingested content into wiki articles. The text content of pages you clip is sent to whichever LLM provider is configured on your server. No data is sent to any other third party.

## Data you can delete

You can delete any ingested source or compiled article through the WikiMind web interface or API. Self-hosted users can delete all data by removing the `~/.wikimind/` directory.

## Analytics and tracking

WikiMind does not include any analytics, telemetry, or tracking. The browser extension does not collect usage statistics.

## Contact

For questions about this policy, open an issue at [github.com/manavgup/wikimind](https://github.com/manavgup/wikimind/issues).
