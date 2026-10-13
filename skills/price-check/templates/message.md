# Message formats

**These are produced by `scripts/price_check.py`.** The agent sends the script's output verbatim and never writes these by hand. This file documents what Chris will see. If you change a format, change `msg_*` in the script and the tests together.

Plain text for Telegram, with no Markdown tables. Prices are always `$X.XX`. URLs sit on their own line so Telegram makes them tappable. Delivery is shown as `free del`, `+ $9.95 del` or `+ del?` (unknown). An offer carried forward from a previous run (its page couldn't be rechecked) ends with `⚠ not rechecked`.

Arrows: `↓` price fell, `↑` price rose, `=` unchanged, `new` entered the top 3.

## Baseline (first run for a product)

```
🆕 Now tracking: Ray-Ban Wayfarer RB2140
Best 3 of 4 AU retailers:

1. Sunglass Hut — $205.00 (free del)
https://www.sunglasshut.com/au/x
2. eBay – optical_au — $208.00 (+ del?)
https://www.ebay.com.au/itm/1
3. David Jones — $208.95 (+ $9.95 del)
https://www.davidjones.com/x

Range: $205.00 – $259.00
Checking weekly (Mondays). I'll only message you when a price moves.
```

## Change alert

📉 if the lowest price fell, 📈 if it rose, otherwise 🔄 ("best still $X"). It lists every change, then the current top 3.

What triggers an alert:
- a top-3 retailer's total changes
- a retailer enters or leaves the top 3
- the range high changes
- a retailer is dropped after 3 runs without a recheck

```
📉 Ray-Ban Wayfarer RB2140 — best now $189.00 (was $205.00)

What changed:
• Sunglass Hut: $205.00 → $189.00 (↓$16.00)
• eBay – optical_au: $208.00 → $212.50 (↑$4.50)

Best 3 now:
1. Sunglass Hut — $189.00 (free del) ↓
https://www.sunglasshut.com/au/x
2. David Jones — $208.95 (+ $9.95 del) =
https://www.davidjones.com/x
3. eBay – optical_au — $212.50 (+ del?) ↑
https://www.ebay.com.au/itm/1

Range: $189.00 – $259.00 across 4 retailers
```

Other change lines:
```
• Myer entered the top 3 at $219.00
• Sunglass Hut left the top 3 (now $229.00 | out of stock | listing gone | no longer matches: … | could not be checked for 3 runs)
• Range high: $260.00 → $270.00
• Big W could not be checked for 3 runs (removed)
```

## No change

The cron reply is `[SILENT]`, so nothing is delivered. "Check X now" uses `--always-message`:
```
No change since Mon 12 Oct 8:50am. Ray-Ban Wayfarer RB2140 — now:
1. ...
Range: $189.00 – $259.00 across 4 retailers
```

## No results

```
⚠️ Ray-Ban Wayfarer RB2140: no qualifying AU offers found this run.
Kept the previous result from Mon 12 Oct 8:50am. The search may need adjusting (try a model number or barcode), retailer pages may be blocked, or the product may be discontinued.
```

## Current (`show`)

```
Ray-Ban Wayfarer RB2140 — as of Tue 13 Oct 8:50am
1. Sunglass Hut — $189.00 (free del)
https://...
2. ...
3. ...
Range: $189.00 – $259.00 across 4 retailers
```

## Product list (`list`)

```
Tracking 1 product:

1. Ray-Ban Wayfarer RB2140 — model RB2140 — weekly (Mondays)
   Best: $189.00 at Sunglass Hut (checked 13 Oct)
```
