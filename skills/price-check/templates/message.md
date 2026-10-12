# Message formats

Plain text for Telegram. No Markdown tables. Prices always `$X.XX`. Keep URLs on their own line so Telegram makes them tappable. Show delivery as `free del`, `+ $9.95 del`, or `+ del?` (unknown).

Arrows: `↓` price fell, `↑` price rose, `=` unchanged, `new` entered the top 3.

## Baseline (first run for a product)

```
🆕 Now tracking: <name>
Best 3 of <retailers> AU retailers:

1. <retailer> — $<total> (<delivery>)
<url>
2. <retailer> — $<total> (<delivery>)
<url>
3. <retailer> — $<total> (<delivery>)
<url>

Range: $<low> – $<high>
Checking <cadence>. I'll only message you when a price moves.
```

## Change alert

Lead with 📉 if the lowest price fell, 📈 if it rose, otherwise 🔄. Then list every change, then the current top 3.

```
📉 <name> — best now $<new low> (was $<old low>)

What changed:
• <retailer>: $<old> → $<new> (↓$<diff>)
• <retailer> entered the top 3 at $<total>
• <retailer> left the top 3 (now $<total> | out of stock | listing gone)
• Range high: $<old> → $<new>

Best 3 now:
1. <retailer> — $<total> (<delivery>) <arrow>
<url>
2. <retailer> — $<total> (<delivery>) <arrow>
<url>
3. <retailer> — $<total> (<delivery>) <arrow>
<url>

Range: $<low> – $<high> across <retailers> retailers
```

Example:

```
📉 Ray-Ban Wayfarer RB2140 — best now $189.00 (was $205.00)

What changed:
• Sunglass Hut: $205.00 → $189.00 (↓$16.00)
• eBay – optical_au: $208.00 → $212.50 (↑$4.50)

Best 3 now:
1. Sunglass Hut — $189.00 (free del) ↓
https://www.sunglasshut.com/au/...
2. David Jones — $208.95 (+ $9.95 del) =
https://www.davidjones.com/...
3. eBay – optical_au — $212.50 (+ del?) ↑
https://www.ebay.com.au/itm/...

Range: $189.00 – $259.00 across 7 retailers
```

## No results

```
⚠️ <name>: no qualifying AU offers found this run.
Kept the previous result from <previous checked_at>. The search may need adjusting (try a model number or barcode), or the product may be discontinued.
```

## Current (ad hoc "price of X?")

```
<name> — as of <checked_at, e.g. Mon 12 Oct 8:03am>
1. <retailer> — $<total> (<delivery>)
<url>
2. ...
3. ...
Range: $<low> – $<high> across <retailers> retailers
```

## Product list (ad hoc "what's tracked?")

```
Tracking <n> products:

1. <name> — <search_type> <query> — <cadence><, paused>
   Best: $<low> at <retailer> (checked <date>)
2. ...
```
