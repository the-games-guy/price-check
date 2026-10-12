# Price Check

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill that tracks Australian retail prices and messages you on Telegram when a price moves.

- Track products by **name, model, SKU or barcode**.
- Per-product cadence: daily, every other day, weekly, fortnightly or monthly (one Hermes cron job each).
- Each check finds the **3 cheapest AU retailers** (new items, delivery included, one result per retailer) and the **price range** across all retailers found.
- A Telegram message only when something moves, up or down. Otherwise the run is silent.
- Ask any time: "what am I tracking?", "price of X?", "check X now".
- Only the latest result per product is stored (no price history).

## Layout
```
skills/price-check/
  SKILL.md                     # procedures and hard rules for the agent
  references/schemas.md        # products.json and snapshot JSON formats
  references/retailers-au.md   # AU retailer names/domains and comparison sites
  templates/message.md         # Telegram message formats
install.md                     # NucBox setup
```

Setup: see [install.md](install.md).

## Phases
- **Phase 1 (this):** skill only. The agent searches, verifies each price on the retailer's page, compares with the last snapshot and formats the message.
- **Phase 2 (if needed):** a small helper script for exact filtering, maths and comparison, plus Google Shopping (SerpApi) and eBay API sources. It uses the same data files.
