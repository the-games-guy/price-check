# Price Check

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill that tracks Australian retail prices and messages you on Telegram when a price moves. It's installed as a skill on Amy (the `assistant` profile on ZORO). It doesn't get its own agent.

- Track products by **name, model, SKU or barcode**. Barcodes are checksum-validated.
- Each product has its own cadence: daily, every other day, weekly, fortnightly or monthly. That's one Hermes cron job per product, at 8am with an off-the-hour minute.
- Each check finds the **3 cheapest AU retailers** (new items, delivery included, one result per retailer) and the **price range** across all retailers found.
- You get a Telegram message only when something moves, up or down. Otherwise the run is silent.
- Ask any time: "what am I tracking?", "price of X?", "check X now".
- Only the latest result per product is stored. There's no price history.

## How it's split
- **Amy (LLM):** finds retailer pages, opens them and records what each one shows (URL, title, price, delivery, seller, stock). Writes that to an offers file.
- **`scripts/price_check.py` (Python standard library):** filtering, one offer per retailer, all maths, ranking, comparison with the last run, saving, and every message. Amy sends its output verbatim.

The script never invents a price, and the LLM never decides whether a price "moved". A retailer whose page didn't load is carried forward, not reported as a change, so search luck can't cause a false alert.

## Layout
```
skills/price-check/
  SKILL.md                     # procedures and hard rules for the agent
  scripts/price_check.py       # deterministic helper (stdlib only)
  references/schemas.md        # offers file, products.json and snapshot formats
  references/retailers-au.md   # AU retailers and comparison sites
  templates/message.md         # what the messages look like (produced by the script)
tests/test_price_check.py      # python3 -m unittest discover -s tests
install.md                     # ZORO / Amy setup
docs/plan.md                   # original design notes
```

Setup: see [install.md](install.md).

## Phases
- **Phase 1 (this):** skill plus the helper's compare/rank/format half. Amy's web tools do the searching. No API keys.
- **Phase 2 (if coverage is poor):** add SerpApi Google Shopping and the eBay Browse API as extra sources in the helper. They write into the same offers format, so nothing else changes. The most likely trigger is AU retailers blocking automated browsing.
