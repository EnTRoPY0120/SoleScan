# Indian Sneaker Price Finder

A localhost-only price comparison app for checking a requested UK sneaker size across Indian official stores, boutiques, and fashion marketplaces. Results stream as retailers finish; one failed or blocked store never stops the others.

## Quick start

Requirements: [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Compose and [mise](https://mise.jdx.dev/).

On Windows/WSL, enable **Settings → Resources → WSL integration** for the distribution containing this repository. Confirm that both `docker version` and `docker compose version` work inside WSL. No host Python, Node, Chromium, or Linux browser libraries are required; the image includes version-matched Playwright Chromium and its dependencies.

```bash
mise run start
```

The command builds the frontend and application image, applies database migrations, waits for the health check, and prints the local URL: <http://127.0.0.1:8000>.

```bash
mise run logs   # follow application logs
mise run stop   # stop containers
mise run test   # backend tests, frontend tests, Svelte checks, production build
```

Runtime SQLite data and logs persist in the repository's `data/` and `logs/` directories. The application container runs as a non-root user and the published port is bound to localhost only.

## API

- `POST /api/search` — create a job
- `GET /api/search/{id}/events` — SSE retailer progress
- `GET /api/search/{id}` — current accumulated result
- `POST /api/search/{id}/refresh` — repeat and bypass the ten-minute cache
- `GET /api/retailers` — configured source health
- `GET /api/health` — readiness

Prices are integer paise internally. Ranking uses list price minus automatic discount plus known shipping. Conditional promotions are disclosed but excluded. Unknown-shipping offers rank behind comparable known delivered totals.

## Retailer collection policy

New Balance uses the searchable Indian catalog operated by its authorized Indian retailer, Brandman Retail, and is identified as **New Balance · Brandman** in source status. Brandman remains a separate retailer with links to its own product pages; it is not represented as a New Balance-owned website. Converse uses its storefront GraphQL catalog. Reebok, Foot Locker, AJIO, Myntra, and Nykaa Fashion use isolated browser contexts inside one shared Chromium process; the remaining stores use ordinary pages and embedded structured data.

Collectors distinguish valid zero-result pages from timeouts, missing pages, and verification challenges. They do not bypass authentication, CAPTCHAs, access controls, or anti-bot restrictions, so genuine transient blocking appears as a concise per-retailer error.

Runtime databases, logs, caches, browser state, build output, and dependencies are ignored by Git. Logs record retailer IDs and error classes, never cookies or credentials.
