# Sneaker Price Finder - Implementation Summary

## Overview
Implemented comprehensive resilience and partial results handling for the sneaker price finder backend and frontend.

## Changes Implemented

### 1. Backend - Base Adapter (`backend/app/adapters/base.py`)
- Added `adapter_type` field to `RetailerDefinition` dataclass
- Enhanced `RateLimitedClient` with:
  - Persisted state via SQLite (`SourceHealthRow`)
  - Exponential doubling cooldowns (up to 24 hours)
  - Half-open circuit breaker state
  - Better recovery after cooldown periods
- Added `half_open` field to `HostState` dataclass

### 2. Database Schema (`backend/app/db.py`)
- Added new `SourceHealthRow` table to persist circuit breaker state:
  - `host` (primary key)
  - `failures` (failure count)
  - `cooldown_until` (expiry timestamp)
  - `reason_code` (failure reason)
  - `updated_at` (last update time)

### 3. Schemas (`backend/app/schemas.py`)
- Added `"partial"` state to `RetailerStatus.state` Literal
- Added `source` and `retry_at` fields to `RetailerStatus`
- Added `paused` and `retry_at` fields to `RetailerInfo`

### 4. Puma Adapter (`backend/app/adapters/puma.py`)
- Added `PartialResultError` exception class for partial successes
- Added `PUMA_SEMAPHORE` for per-host concurrency limiting (2 concurrent requests)
- Enhanced `search()` to handle individual product failures gracefully
- Returns valid offers even when some products fail to parse
- Updated `PumaAdapter.definition` to include `adapter_type="puma"`

### 5. Adapter Registry (`backend/app/adapters/registry.py`)
- Replaced if/elif branching with clean factory function `_build_adapter()`
- All adapters now use `adapter_type` field for instantiation
- Updated all retailer definitions with explicit `adapter_type` values

### 6. Brandman, VegNonVeg Adapters
- Added `adapter_type="brandman"` to `BrandmanAdapter.definition`
- Added `adapter_type="vegnonveg"` to `VegNonVegAdapter.definition`

### 7. Browser Adapter (`backend/app/adapters/browser.py`)
- Added `_preflight()` method for HTTP checks before opening browser
- Enhanced error diagnostics:
  - HTTP/2 protocol errors
  - net::ERR_* errors
  - Missing Chromium dependencies
  - Generic browser errors with better messages

### 8. Search Manager (`backend/app/search.py`)
- Added handling for `PartialResultError` in `_run_adapter()`
- Partial results set state to `"partial"` and include valid offers
- Updated event emission to treat partial as success

### 9. API Endpoints (`backend/app/main.py`)
- Updated `/api/retailers` to expose:
  - `paused` status (based on cooldown state)
  - `retry_at` timestamp (when retailer becomes available)

### 10. Frontend Types (`frontend/src/lib/types.ts`)
- Added `"partial"` to `RetailerStatus.state` union type
- Added `source` and `retry_at` fields to `RetailerStatus`

### 11. Frontend UI (`frontend/src/lib/components/RetailerStatusItem.svelte`)
- Enhanced status messages:
  - `partial`: "Partial results (some products unavailable)"
  - `blocked` with `verification_challenge`: "Access blocked — verification challenge"
  - `blocked` with `host_cooldown`: "Auto-paused"
  - `blocked` with `http_403`/`http_401`: "Access denied by retailer"
  - `error` with `transport_protocol`: "Transport error (HTTP/2 incompatibility)"
  - `error` with `catalog_shell`: "Retailer layout has changed"
  - `error` with `catalog_contract_changed`: "Retailer catalog format changed"
  - `complete` with 0 offers: "No results found"
- Added styling for `partial` state (warning yellow)

### 12. Tests
Added comprehensive test coverage:
- `test_puma_partial_success_one_bad_product` - Verifies PartialResultError behavior
- `test_partial_result_is_reported_as_partial_state` - Search manager partial handling
- `test_repeated_403_doubles_cooldown` - Exponential backoff verification
- `test_half_open_success_closes_circuit` - Circuit breaker recovery

## Key Features

### Circuit Breaker with Persistence
- Host-level circuit breaker persists across restarts
- Exponential doubling of cooldown periods (up to 24 hours)
- Half-open state allows testing if host has recovered
- Automatic closure when requests succeed after cooldown

### Partial Results
- Puma adapter returns valid products even if some fail
- Users see available offers instead of complete failure
- Clear UI indication of partial results

### Better Diagnostics
- Specific error messages for different failure types
- Browser adapter preflight checks to avoid unnecessary browser launches
- Enhanced HTTP/2 and network error classification

## Test Results
All tests passing: **46 passed, 11 skipped**
- Partial result handling: ✅
- Exponential cooldowns: ✅
- Half-open recovery: ✅
- All existing tests: ✅

## Migration Notes
- New `source_health` table created automatically via `init_db()`
- Backward compatible - all changes are additive
- No data migration required
