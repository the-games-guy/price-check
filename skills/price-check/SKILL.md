---
name: price-check
description: Track Australian retail prices for products (by name, model, SKU or barcode) on a schedule and alert via Telegram only when a price moves up or down. Also answers ad hoc questions like "list my products" or "what's the price of X?".
version: 0.1.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [shopping, prices, monitoring, australia]
    category: shopping
---

# Price Check (AU)

Track the best Australian prices for products the user cares about. Each tracked product has its own cron job. A run checks retailers, compares against the last snapshot, and either stays silent or sends one alert describing exactly what moved.

All state lives in `~/.hermes/data/price-check/`:
- `products.json` — tracked products and their settings
- `snapshots/<slug>.json` — the last result for each product (only the latest; no history)

Exact JSON schemas: `references/schemas.md`. Message formats: `templates/message.md`. Retailer name and domain hints: `references/retailers-au.md`. Read these before writing any file or message.

## When to Use
- The user asks to track, watch or monitor a product's price ("track the Ray-Ban RB2140 weekly", "watch barcode 9300601234567 daily").
- A cron job prompt says to run the price-check procedure for a product slug.
- The user asks what is tracked, the current price of a tracked product, or to change, pause, resume, re-run or stop tracking.

## Hard rules (apply to every run)
1. **Never state a price from memory.** Every price must come from a page you opened in *this* run (record its URL). A search-result snippet alone is not enough; open the page.
2. **Australia, AUD only.** Retailers must ship to Australia and price in AUD. Skip overseas stores and any non-AUD price.
3. **New items only.** Skip used, refurbished, renewed, pre-owned, open-box, ex-display or "grade B" listings.
4. **Exact product only.** The page must match the product's identifier (barcode, model or SKU appears on the page) or, for name searches, contain every `include` keyword and none of the `exclude` keywords. Wrong colour, size, bundle, pack quantity or generation = skip.
5. **In stock for delivery.** Skip "out of stock", "sold out", "pre-order" and in-store-only listings. Record them in `unavailable` (see schema) so a retailer that drops out can be reported.
6. **Total = price + delivery** to a standard metro address. Free delivery = 0. If delivery cost genuinely cannot be determined, set `delivery` to null and use the item price as the total.
7. **One offer per retailer.** Normalise retailer names (see `references/retailers-au.md`) and keep only the cheapest qualifying offer per retailer. eBay and other marketplaces count each seller as a separate retailer: `eBay – <seller>`, `Amazon AU – <seller>` (`Amazon AU` when sold by Amazon).
8. **Respect min/max price** filters on the total, when set.
9. **Money is two decimals.** Compute totals and differences carefully; re-check arithmetic before writing.
10. **Write JSON exactly to schema.** Read the existing file first and preserve fields you are not changing.

## Procedure A — Track a new product
1. Gather from the user (ask only for what is missing):
   - what to search by: `name`, `model`, `sku` or `barcode`, and the value
   - cadence: `daily`, `every_other_day`, `weekly`, `fortnightly` or `monthly` (default `weekly`)
   - optional: include/exclude keywords, min/max price, a display name
   For a barcode, strip spaces and dashes; it must be 8, 12, 13 or 14 digits. For SKU, warn once that retailer-specific SKUs rarely match other stores and suggest model or barcode if known.
2. Create a slug: lowercase display name, non-alphanumerics → `-`, max 40 chars, unique within `products.json` (append `-2` etc. if taken).
3. Add the product to `products.json` (create the directory and file if missing) per the schema, with `active: true` and `cron_job_id: null`.
4. Create the cron job with the `cronjob` tool:
   - `action="create"`, `name="price-check: <display name>"`, `skills=["price-check"]`, `deliver="telegram"`
   - `schedule` from the table below
   - `prompt` exactly: `Run the price-check skill's Procedure B for product slug "<slug>". Follow the skill's hard rules. If the result is NO_CHANGE, reply with only [SILENT]. Otherwise reply with only the alert message.`
5. Save the returned job id into the product's `cron_job_id`.
6. Run Procedure B now for this slug and send the baseline message to the user in this chat.
7. Confirm: what is tracked, how it is searched, the cadence and the job id.

| Cadence | `schedule` |
|---|---|
| daily | `every day at 8am` |
| every_other_day | `every 2d` |
| weekly | `every monday 8am` |
| fortnightly | `every 14d` |
| monthly | `0 8 1 * *` |

`every 2d` and `every 14d` are intervals counted from when the job is created. If the user wants them at a particular time of day, create the job at that time or tell them it will drift to the creation time.

## Procedure B — Run a price check for `<slug>`
1. Read `products.json` and find the product. If it is missing or `active` is false, reply `[SILENT]` and stop.
2. Read `snapshots/<slug>.json` if it exists (the previous result).
3. **Re-check known retailers first.** For every offer in the previous snapshot's `offers` (all of them, not just the top 3) and every entry in `unavailable`, open its URL and record the current price, delivery and availability. This keeps runs comparable; do not skip it.
4. **Look for other retailers.** Web search for the product in Australia:
   - barcode: search the barcode digits, then `"<barcode>" price`, then the product name found on matching pages
   - model/SKU: search `"<value>" price australia`, `"<value>" buy`
   - name: search `<query> price australia`, `<query> buy online australia`, adding include keywords
   Also try the known retailers in `references/retailers-au.md` relevant to the product category. Open the most promising candidate pages (aim for 6–10 new pages, stop earlier if results are clearly exhausted).
5. Apply every hard rule to every page you opened. Build the offer list per the schema. Keep the cheapest offer per retailer.
6. Sort offers by `total` ascending. `top3` = the first three. `range` = lowest and highest `total` across all offers, plus the count of retailers.
7. **Compare with the previous snapshot** (skip if there is none — this is a baseline):
   - a top-3 retailer's total changed by $0.01 or more (up or down)
   - a retailer entered or left the top 3
   - the range low or high changed by $0.01 or more
   If none of these, the result is NO_CHANGE.
8. Write the new snapshot to `snapshots/<slug>.json` per the schema (overwrite; no history). Update `last_checked` in `products.json`. Write files even on NO_CHANGE so the timestamp is current.
9. If no qualifying offers were found at all, do not overwrite a previous non-empty snapshot. Instead reply with the "no results" message from `templates/message.md` (do not use [SILENT]; the user needs to know the search broke).
10. Reply:
   - NO_CHANGE → only `[SILENT]`
   - baseline → the baseline message
   - change → the change alert, listing every change detected, each with old → new total

## Procedure C — Ad hoc requests
- **"List my products" / "what's tracked?"** Read `products.json` and each snapshot. Reply with the list format in `templates/message.md`: name, search type and value, cadence, active/paused, last checked, current best price and retailer. Do not browse.
- **"Price of X?"** Match X to a tracked product (by name, slug, model or barcode). Reply with the current snapshot (the "current" format) and its `checked_at` time. Offer to run a fresh check. If X is not tracked, offer to track it or do a one-off check (Procedure B without writing any files).
- **"Check X now"** Run Procedure B for it and reply with the result even if NO_CHANGE (say "No change since <time>" plus the current format).

## Procedure D — Change, pause, resume, remove
- **Change cadence:** update `cadence` in `products.json`, then `cronjob(action="update", job_id=<cron_job_id>, schedule=<new schedule>)`.
- **Change search terms or filters:** update `products.json`, then delete `snapshots/<slug>.json` and run Procedure B to send a fresh baseline (old comparisons no longer apply).
- **Pause / resume:** set `active`, and `cronjob(action="pause"|"resume", job_id=...)`.
- **Remove:** `cronjob(action="remove", job_id=...)`, delete the product from `products.json` and delete its snapshot.
- If `cron_job_id` is missing or stale, use `cronjob(action="list")` and match on the job name `price-check: <display name>`.

Always confirm the change back to the user.

## Pitfalls
- **Phantom changes from search luck.** A retailer missing from this run's search is not a price change. Only report a retailer as leaving the top 3 if you re-opened its URL (step B3) and it is now more expensive, unavailable, or the page is gone. If its page could not be loaded (timeout, blocked), carry its previous offer forward unchanged, set `"stale": true` and increase `stale_runs` by 1, and do not report it as a change. If `stale_runs` would reach 3, drop the offer instead and report it as "could not be checked for 3 runs" in the alert. Reset `stale_runs` to 0 whenever the page loads.
- **Sale vs member prices.** Use the price any customer pays. Ignore member-only, app-only, coupon-code and "with trade-in" prices. Use a sale price if it applies to everyone.
- **Multi-packs and bundles.** "2-pack", "bundle", "+ case" are different products unless the user asked for them.
- **Price shown ex-GST or per unit.** AU retail prices include GST; if a page shows ex-GST or per-unit pricing, it is probably a trade/wholesale site — skip it.
- **Blocked sites.** Some retailers block automated browsing. Do not guess; skip it (or carry forward as `stale`, see above).
- **Marketplaces.** Check the seller ships from Australia or the listing is priced in AUD with delivery to Australia; skip international sellers with long delivery or extra import fees if the total cannot be determined.

## Verification
- After Procedure A: `products.json` contains the product with a `cron_job_id`, the job appears in `cronjob(action="list")`, and a baseline message was sent.
- A second immediate run of Procedure B should normally result in `[SILENT]`.
- Every price in a message has a URL that was opened in that run.
