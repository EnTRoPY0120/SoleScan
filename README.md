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
- `POST /api/retailers/{retailer_id}/session/start` — open a localhost-only assisted browser for a verification screen
- `POST /api/retailers/{retailer_id}/session/complete` — save the user-cleared browser state and rerun the search
- `DELETE /api/retailers/{retailer_id}/session` — remove the saved retailer browser state

Prices are integer paise internally. Ranking uses list price minus automatic discount plus known shipping. Conditional promotions are disclosed but excluded. Unknown-shipping offers rank behind comparable known delivered totals.

Search interpretation corrects only a unique one-edit spelling mistake in an alphabetic model token. Numbers, brands, sizes, departments, colourways, and postcodes are never changed, and returned offers must still pass exact identity matching. Corrections are disclosed in the results with an option to search the original text; the vocabulary comes from curated models, accepted official-retailer offers, or the same model corroborated by two independent nonofficial retailers.

## Retailer collection policy

New Balance uses the searchable Indian catalog operated by its authorized Indian retailer, Brandman Retail, and is identified as **New Balance · Brandman** in source status. Brandman remains a separate retailer with links to its own product pages; it is not represented as a New Balance-owned website. Converse and ASICS use their storefront catalog APIs. Reebok, Foot Locker, AJIO, Myntra, and Nykaa Fashion prefer isolated browser contexts inside one shared Chromium process; if Chromium hits a protocol failure, Myntra can fall back to its public embedded search data. The remaining stores use ordinary pages and embedded structured data.

All configured sources are attempted automatically. Collectors distinguish valid zero-result pages from timeouts, missing pages, and verification challenges. They do not bypass authentication, CAPTCHAs, access controls, or anti-bot restrictions, so genuine transient blocking appears as a concise per-retailer error. When a browser-backed retailer presents a challenge, the UI can open one isolated headful session through the localhost VNC viewer; users should clear only the visible consent/verification screen and never enter retailer credentials. Saved browser state is stored under `data/browser-sessions` with restrictive permissions.

Runtime databases, logs, caches, browser state, build output, and dependencies are ignored by Git. Logs record retailer IDs and error classes, never cookies or credentials.

Once per day while the app is running, a known-product canary checks retailer contracts and logs degraded retailer IDs. Set `SPF_CANARY_ENABLED=0` to disable it or `SPF_CANARY_INTERVAL_SECONDS` to change the interval. Failure-only diagnostic metadata is retained for seven days; it never includes response bodies, cookies, credentials, or verification-session content.
