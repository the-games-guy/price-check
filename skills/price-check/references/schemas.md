# Data formats

Base directory: `/root/price-check-data/` inside the sandbox. On ZORO it is `/home/zoro/price-check-data/`, which is bind-mounted read-write. The helper honours `PRICE_CHECK_HOME` for host-side runs.

**You only write one file: the offers file.** `products.json` and `snapshots/` are written by the helper and must not be edited by the agent.

## Offers file — `work/<slug>.offers.json` (agent writes, helper reads)

One entry for every retailer page you opened this run.

```json
{
  "offers": [
    {
      "url": "https://www.sunglasshut.com/au/ray-ban/rb2140-901",
      "retailer": "Sunglass Hut",
      "title": "Ray-Ban RB2140 Original Wayfarer Classic Black",
      "price": 189.00,
      "delivery": 0,
      "id_on_page": true,
      "mpn": "RB2140 901 50-22"
    },
    {
      "url": "https://www.ebay.com.au/itm/1234567890",
      "seller": "optical_au",
      "title": "Ray-Ban RB2140 901 Wayfarer 50mm New",
      "price": 199.00,
      "delivery": null,
      "id_on_page": true
    },
    {
      "url": "https://www.davidjones.com/...",
      "title": "Ray-Ban RB2140 Wayfarer",
      "price": 209.00,
      "delivery": 9.95,
      "in_stock": false
    }
  ],
  "unavailable": [
    { "url": "https://www.myer.com.au/...", "retailer": "Myer", "reason": "listing gone" }
  ],
  "failed": [
    { "url": "https://www.jbhifi.com.au/...", "retailer": "JB Hi-Fi", "reason": "blocked" }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `url` | yes | The retailer's own product page (not a comparison site). The helper identifies the retailer from the domain. |
| `title` | yes | Product title as shown on the page. Include/exclude keywords and "used/refurbished" are checked against it. |
| `price` | yes | Item price in AUD as a number, e.g. `189.0`. No `$` signs or text. |
| `delivery` | yes | `0` for free delivery, a number for paid delivery, `null` if it can't be found. |
| `retailer` | for unknown domains | Display name. Retailers in `retailers-au.md` get their canonical name automatically. |
| `seller` | marketplaces | Required for eBay, Amazon AU, Catch and Kogan listings. Use `"Amazon"`, `"Catch"` or `"Kogan"` when the platform itself sells it. |
| `id_on_page` | identifier searches | `true` only if you saw the exact barcode/model/SKU on the page. |
| `gtin`, `mpn` | optional | Copy any barcode or manufacturer part number shown. A mismatch drops the offer. |
| `in_stock` | optional | `false` = out of stock, sold out, pre-order or in-store only. It is moved to `unavailable`. |
| `condition` | optional | Defaults to `"new"`. Anything else is dropped. |
| `currency` | optional | Defaults to `"AUD"`. Anything else is dropped. |

- `unavailable`: pages that exist but can't be bought for delivery. `reason` is shown in alerts, e.g. "out of stock" or "listing gone".
- `failed`: pages that wouldn't load or were blocked. It's for the log only. The helper carries the previous price forward for up to 3 runs whether or not a page is listed here.

A bare JSON list is also accepted and is treated as `offers`.

## `products.json` (helper writes)

```json
{
  "version": 1,
  "products": [
    {
      "slug": "ray-ban-wayfarer-rb2140",
      "name": "Ray-Ban Wayfarer RB2140",
      "search_type": "model",
      "query": "RB2140",
      "include": [],
      "exclude": ["case", "lens"],
      "min_price": null,
      "max_price": null,
      "cadence": "weekly",
      "cron_job_id": "abc123",
      "active": true,
      "created_at": "2026-10-13T08:00:00+11:00",
      "last_checked": "2026-10-13T08:50:12+11:00"
    }
  ]
}
```

| Field | Notes |
|---|---|
| `search_type` | `name`, `model`, `sku` or `barcode`. Barcodes are checksum-validated on `add`. |
| `include` | Every keyword must appear in the listing title (whole words; plurals and spacing tolerated). |
| `exclude` | No keyword may appear in the listing title. |
| `min_price`, `max_price` | Bounds on the total (price + delivery). |
| `cadence` | `daily`, `every_other_day`, `weekly`, `fortnightly` or `monthly`. |

## `snapshots/<slug>.json` (helper writes; latest result only)

```json
{
  "version": 1,
  "slug": "ray-ban-wayfarer-rb2140",
  "checked_at": "2026-10-13T08:50:12+11:00",
  "offers": [
    {
      "key": "sunglasshut.com",
      "retailer": "Sunglass Hut",
      "title": "Ray-Ban RB2140 Original Wayfarer Classic Black",
      "url": "https://www.sunglasshut.com/au/...",
      "price": 189.0, "delivery": 0.0, "total": 189.0,
      "stale": false, "stale_runs": 0
    }
  ],
  "unavailable": [
    { "key": "davidjones.com", "retailer": "David Jones", "url": "https://www.davidjones.com/...",
      "reason": "out of stock", "missed_runs": 0 }
  ],
  "top3": ["sunglasshut.com", "ebay.com.au|optical_au", "theiconic.com.au"],
  "range": { "low": 189.0, "high": 259.0, "retailers": 7 }
}
```

- `key` identifies a retailer across runs: the domain, plus `|seller` for marketplaces. Comparisons use the key, so a retailer's display name can't cause false alerts.
- `stale` / `stale_runs`: the page wasn't rechecked this run, so the previous offer was carried forward. The offer is dropped (and reported) at 3.
- `unavailable` entries are rechecked each run. They're forgotten after 3 runs where they aren't reported.
- `logs/<slug>.last.txt` lists every offer dropped in the last run and why.
