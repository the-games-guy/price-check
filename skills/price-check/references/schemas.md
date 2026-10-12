# Data file schemas

Base directory: `~/.hermes/data/price-check/`. Create it (and `snapshots/`) if missing.

Rules for every write:
- Valid JSON, 2-space indent, UTF-8.
- Money as numbers with two decimals (e.g. `189.0` is fine in JSON but always reason in cents; never store strings like `"$189"`).
- Timestamps in ISO 8601 with the local offset, e.g. `2026-10-12T08:00:00+11:00`.
- Read the existing file first and keep fields you are not changing.

## `products.json`

```json
{
  "version": 1,
  "products": [
    {
      "slug": "ray-ban-wayfarer-rb2140",
      "name": "Ray-Ban Wayfarer RB2140",
      "search_type": "model",
      "query": "RB2140",
      "include": ["wayfarer"],
      "exclude": ["case", "lens", "replacement"],
      "min_price": null,
      "max_price": null,
      "cadence": "weekly",
      "cron_job_id": "abc123",
      "active": true,
      "created_at": "2026-10-12T08:00:00+11:00",
      "last_checked": "2026-10-12T08:03:12+11:00"
    }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `slug` | string | Unique, lowercase, `a-z0-9-`, ≤ 40 chars. Snapshot file name. |
| `name` | string | Display name used in messages. |
| `search_type` | `"name"` \| `"model"` \| `"sku"` \| `"barcode"` | |
| `query` | string | Search text, model, SKU, or barcode digits only. |
| `include` | string[] | Name searches: every keyword must appear on the product page (case-insensitive). May be empty. |
| `exclude` | string[] | No keyword may appear in the product title. May be empty. |
| `min_price`, `max_price` | number \| null | Bounds on the total (price + delivery). |
| `cadence` | `"daily"` \| `"every_other_day"` \| `"weekly"` \| `"fortnightly"` \| `"monthly"` | |
| `cron_job_id` | string \| null | Hermes cron job id. |
| `active` | boolean | `false` = paused. |
| `created_at`, `last_checked` | string \| null | ISO 8601. |

## `snapshots/<slug>.json`

The latest result only. Overwrite on each run.

```json
{
  "version": 1,
  "slug": "ray-ban-wayfarer-rb2140",
  "checked_at": "2026-10-12T08:03:12+11:00",
  "offers": [
    {
      "retailer": "Sunglass Hut",
      "title": "Ray-Ban RB2140 Original Wayfarer Classic Black",
      "url": "https://www.sunglasshut.com/au/...",
      "price": 189.0,
      "delivery": 0.0,
      "total": 189.0,
      "stale": false,
      "stale_runs": 0
    },
    {
      "retailer": "eBay – optical_au",
      "title": "Ray-Ban RB2140 901 Wayfarer 50mm New",
      "url": "https://www.ebay.com.au/itm/...",
      "price": 199.0,
      "delivery": null,
      "total": 199.0,
      "stale": false,
      "stale_runs": 0
    }
  ],
  "unavailable": [
    {
      "retailer": "David Jones",
      "url": "https://www.davidjones.com/...",
      "reason": "out of stock"
    }
  ],
  "top3": ["Sunglass Hut", "eBay – optical_au", "The Iconic"],
  "range": { "low": 189.0, "high": 259.0, "retailers": 7 }
}
```

| Field | Notes |
|---|---|
| `offers` | Every qualifying offer, one per retailer, sorted by `total` ascending. |
| `offers[].delivery` | `0.0` for free delivery, `null` if unknown (then `total` = `price`). |
| `offers[].stale` / `stale_runs` | Page could not be loaded this run, so the previous offer was carried forward. Dropped once `stale_runs` reaches 3. |
| `unavailable` | Known retailer pages that exist but are out of stock / pre-order / in-store only. Re-checked each run. |
| `top3` | Retailer names of the first three `offers` (fewer if fewer offers). |
| `range` | `low` and `high` over all `offers[].total`, `retailers` = number of offers. |
