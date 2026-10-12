# Price Check — a Hermes Agent skill on the NucBox

## Context
You want to track Australian retail prices for products you choose and get a Telegram message whenever a price moves, up or down. Instead of a standalone app, this runs as an agent skill inside **Hermes Agent**, which is already hosted on your NucBox.

**Requirements carried over from the earlier discussion**
- Australian retailers, prices in AUD.
- New items only.
- Prices include delivery.
- One result per retailer.
- Each result shows the 3 cheapest retailers and the price range (lowest → highest).
- Search by name, model, SKU or barcode.
- A cadence per product: daily, every other day, weekly, fortnightly or monthly.

**New decisions**
- Hermes replaces the web UI, database, scheduler and email.
- Messages go to Telegram, and only when a price has moved. There is no regular summary.
- Product lists and current prices are available on request in chat.
- Only the last snapshot per product is kept, for comparison. There is no price history.

**What Hermes provides** (confirmed from the Hermes docs)
- **Skills:** `SKILL.md` folders under `~/.hermes/skills/`, or extra directories added with `skills.external_dirs` in `~/.hermes/config.yaml`.
- **Cron jobs:**
  - `hermes cron create <schedule> <prompt> --skill <name> --name <n> --deliver telegram`.
  - Each job runs in a fresh session, so its prompt must be self-contained.
  - If the agent's reply contains `[SILENT]`, nothing is delivered. Failed runs are always delivered.
- **Agent tools:** the agent can manage cron jobs itself through its `cronjob` tool, run commands in a terminal, and search and browse the web.
- **Credentials:** cron scripts do **not** inherit provider credentials, so the helper script loads its own API keys.

## Phase 1 (build now): skill only, no Python
The repo contains only Markdown: `skills/price-check/SKILL.md`, `references/retailers-au.md`, `templates/` and `install.md`. The agent does everything with its built-in tools: web search, browsing, reading and writing files, and the `cronjob` tool.

Data uses the same files as the design below, written by the agent:
- `~/.hermes/data/price-check/products.json`
- `~/.hermes/data/price-check/snapshots/<slug>.json`

Their JSON schemas are spelled out in `references/schemas.md`, so every run reads and writes the same structure.

**Rules in SKILL.md that make up for having no script**
1. **Recheck known retailers first.** Each run reopens the URLs saved in the last snapshot before searching for new retailers. Without this, which retailers a search happens to find changes from run to run, and that alone would trigger false "price moved" messages.
2. **Verify every price.** Each price must come from a page opened during this run, with its URL. Anything else is dropped.
3. **Fixed procedure.** A step-by-step checklist for filtering, one result per retailer, totals and change detection, plus a fixed Telegram message format in `templates/message.md`.
4. **Explain each alert.** Every alert names what changed (retailer, old total → new total), so a wrong alert is easy to spot.
5. **Barcode searches.** The agent searches for the barcode itself and checks it appears on each product page. It cannot validate the checksum, so a mistyped barcode is only noticed when the search finds nothing.

**What Phase 1 doesn't have:** the SerpApi and eBay API sources, an exact barcode checksum, and fully consistent maths and comparisons.

**When to add the helper script (Phase 2):** if over the first couple of weeks you see false alerts, missed retailers or wrong totals, add the deterministic helper described below. The data files stay the same, so nothing needs migrating.

## Phase 2 design (later, only if needed): the LLM agent plus a deterministic helper script
The LLM does what it is good at:
- finding retailers across the web
- opening product pages and confirming the price, stock, variant and delivery cost
- chatting with you

A small Python helper does everything that must be exact:
- calling the shopping APIs
- filtering
- choosing one offer per retailer
- ranking
- comparing with the last snapshot
- formatting the message

This keeps runs consistent, stops the model from inventing prices or doing arithmetic, and copes with a smaller local model.

### Where prices come from
1. **SerpApi Google Shopping** (`gl=au`). This gives broad retailer coverage and works well for barcode and model searches. You'll need an API key; the free tier suits a few weekly products.
2. **eBay Browse API** (`EBAY_AU`, new condition, fixed price). It's free and supports searching by barcode (GTIN).
3. **The agent's own web search and browsing.** It finds AU retailers the APIs missed (JB Hi-Fi, Big W, Baby Bunting, Sunglass Hut and so on) and opens each top candidate's page to verify it. If a site blocks it, the agent keeps the API price and marks it as unverified, rather than guessing.

## Repo layout (the repo becomes the skill package)
```
skills/price-check/
  SKILL.md                 # procedures for the agent (see below)
  scripts/price_check.py   # helper CLI; Python standard library only, so no extra installs on the NucBox
  references/retailers-au.md   # known AU retailer domains and name normalisation hints
tests/
  fixtures/                # recorded SerpApi and eBay JSON
  test_price_check.py      # pytest
install.md                 # NucBox setup steps
.env.example               # SERPAPI_KEY, EBAY_CLIENT_ID, EBAY_CLIENT_SECRET
```
On the NucBox you clone the repo and add `<clone>/skills` to `skills.external_dirs`. Updating later is just `git pull`.

## Helper CLI (`price_check.py`)
**Data:** everything lives under `~/.hermes/data/price-check/` (configurable with `PRICE_CHECK_HOME`).
- `products.json` holds each product's settings: `slug, name, search_type (name|model|sku|barcode), query, include[], exclude[], min_price, max_price, cadence, cron_job_id, active`.
- `snapshots/<slug>.json` holds the last result only.

**Keys:** read from `~/.config/price-check/.env` or from environment variables.

| Command | Purpose |
|---|---|
| `add --name … --type barcode --query 9300…  --cadence weekly [--include …] [--exclude …] [--min …] [--max …]` | Validates the input (GTIN checksum, model normalisation) and saves the product. Prints its slug and the matching cron schedule. |
| `set-job <slug> <job_id>` / `update <slug> …` / `remove <slug>` / `pause` / `resume` | Manage a product. |
| `list` | Shows each product with its cadence, last check, current lowest price and top retailer. Used for ad hoc questions. |
| `search <slug>` | Calls SerpApi and eBay, then normalises and filters the results. Prints candidate offers as JSON for the agent to check. |
| `commit <slug> --offers <file>` | Takes the agent's verified offer list (JSON), filters it again, keeps one offer per retailer, ranks by total, and builds the top 3 and price range. It compares this with the snapshot, saves the new snapshot, and prints either `NO_CHANGE` or a ready-to-send Telegram message. |
| `show <slug>` | Shows the current snapshot, formatted, for "what's the price of X?" questions. |

**Rules in the helper**
- **Search types:**
  - **Barcode:** EAN-13, UPC-A, EAN-8 or GTIN-14. The checksum is validated and the code normalised to GTIN-14.
  - **Model and SKU:** normalised by ignoring case, spaces and hyphens.
  - **Identifier searches:** an offer is dropped if its GTIN or MPN conflicts with the one searched for. An offer with no identifier is kept only if the identifier appears in its title.
  - **Name searches:** use the include/exclude keywords and the min/max price.
- **Offer fields:** `source, retailer, title, url, price, delivery|null, total, condition, verified`.
  - Only AUD prices are kept.
  - Titles containing used, refurbished, pre-owned or renewed are dropped.
  - `total = price + delivery`. If delivery is unknown, the total is the price and the message shows "+ delivery".
- **One per retailer:**
  - Retailer names are normalised (e.g. "JB Hi-Fi" and "jbhifi.com.au" count as one).
  - eBay offers are keyed per seller.
  - The cheapest offer for each retailer is kept.
- **Change detection (what triggers a message):**
  - any top-3 retailer's total goes up or down
  - a retailer enters or leaves the top 3
  - the lowest or highest price in the range changes
  - The first run always sends a baseline message.
  - Changes under $0.01 are ignored. There is an optional `--min-move` threshold, default 0, matching your "any move" choice.
- **Telegram message:** plain text that is easy to read on a phone. Example:
  ```
  📉 Ray-Ban Wayfarer RB2140 — best now $189.00 (was $205.00)
  1. Sunglass Hut — $189.00 (free delivery) ↓$16.00  <url>
  2. David Jones — $199.00 + $9.95 del = $208.95 =     <url>
  3. eBay – optical_au — $212.50 ↑$4.50               <url>
  Range: $189.00 – $259.00 across 7 retailers
  ```

## SKILL.md — what the agent is told to do
1. **Track a product.** When you say something like "track X by barcode 9300… weekly":
   - Run `add`.
   - Create a cron job with the `cronjob` tool, using the schedule from `add`, `skills=["price-check"]` and `deliver="telegram"`. The job's prompt is self-contained: *"Run the price-check procedure for product `<slug>`. If the helper prints NO_CHANGE, reply only [SILENT]; otherwise reply with the helper's message verbatim."*
   - Run `set-job` to record the job ID.
   - Run the check once straight away so you get the baseline message.
2. **Price-check procedure** (used by each cron run):
   - Run `search <slug>` to get the API candidates.
   - Search the web for further AU retailers selling that exact item, using the barcode or model where there is one.
   - Open the pages of the best 6–8 candidates and confirm the price, the delivery cost, that the item is in stock, that it is new, and that it is the exact variant.
   - Every offer must come from a page the agent actually opened, or from the API. No price may come from the model's memory.
   - Write the offers to a temporary JSON file and run `commit`.
   - Reply `[SILENT]` on NO_CHANGE; otherwise send the message exactly as the helper printed it.
3. **Ad hoc requests:**
   - "List my products" or "what's tracked?" → run `list`.
   - "Price of X?" → run `show`, and offer to run a check now.
4. **Changes:** change cadence, pause, resume or remove → update both the helper and the cron job.

**Cadence → Hermes schedule** (all checks at 08:00 local time)

| Cadence | Schedule |
|---|---|
| daily | `0 8 * * *` |
| every other day | `0 8 */2 * *` |
| weekly | `0 8 * * 1` |
| fortnightly | `every 14d` |
| monthly | `0 8 1 * *` |

During the build I'll check against `hermes cron create --help` that `every 14d` is valid. If it isn't, fortnightly falls back to a weekly job that the helper skips on alternate weeks.

## Build order (Phase 1)
1. `SKILL.md`:
   - how to track a product, the price-check procedure, ad hoc requests and changes
   - the cadence → schedule table
2. `references/schemas.md` and `references/retailers-au.md`.
3. `templates/message.md`.
4. `install.md`:
   - adding `external_dirs` to the Hermes config
   - checking the Telegram home channel
   - a test run with `hermes cron run <id>`
5. Commit and push to `claude/product-price-comparison-349yt2`.

**Verifying Phase 1** happens on the NucBox:
1. Ask Hermes to track a product. The baseline message should arrive and the cron job should appear in `hermes cron list`.
2. Run the job again straight away with `hermes cron run <id>`. It should stay silent.
3. Edit a price in the snapshot by hand and run the job again. You should get a ↑/↓ message.
4. Ask "list my products" and check the reply.

## Phase 2 build order (later)
1. `price_check.py`, in order:
   - data store and product commands
   - search-type validation
   - SerpApi and eBay clients
   - filter, one-per-retailer and rank
   - snapshot comparison
   - message formatter
2. pytest coverage with recorded fixtures (details under Verification).
3. `SKILL.md` and `references/retailers-au.md`.
4. `install.md`:
   - getting a SerpApi key and an eBay developer keyset
   - the `.env` file
   - `external_dirs` in the Hermes config
   - checking that the Telegram gateway has a home channel set
   - a test run with `hermes cron run <id>`
5. Commit and push to `claude/product-price-comparison-349yt2`.

## Verification
- **`pytest`, using recorded fixtures:**
  - GTIN checksums (valid and invalid)
  - model and identifier matching
  - new-only filtering and keyword/price filters
  - delivery totals and one per retailer
  - top 3 and range
  - comparison cases: first run (baseline), no change (`NO_CHANGE`), a rise, a fall, a retailer swap, and a change in the high end of the range
  - message formatting
- **CLI smoke test with live keys:**
  - `add` a real product by barcode, then run `search` and check the candidates are that exact item.
  - Run `commit` twice: the first prints the baseline message, the second prints `NO_CHANGE`.
  - Edit a price in the snapshot by hand and check that a ↑/↓ message is produced.
- **On the NucBox:**
  - Ask Hermes on Telegram to "track <product> by barcode weekly". Check that `hermes cron list` shows the job and that the baseline message arrives.
  - `hermes cron run <id>` should give a silent run, with no Telegram message and the output saved in `~/.hermes/cron/output/`.
  - Asking "list my products" should return the tracked list.
