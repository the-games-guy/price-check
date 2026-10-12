# Install on the NucBox (Hermes Agent)

Phase 1 is a skill only: Markdown instructions, no code, no API keys. Hermes does the searching, browsing, file writing and scheduling with its built-in tools.

## Prerequisites
- Hermes Agent running on the NucBox with the **Telegram gateway** set up (`hermes gateway setup`, `hermes gateway start`).
- Hermes has working **web search / browsing** tools (`hermes tools` to check). The skill depends on opening retailer pages.
- A model that handles multi-step tool use well. If runs are unreliable on a local model, point these cron jobs at a stronger hosted model.

## 1. Clone the repo
```bash
git clone https://github.com/the-games-guy/price-check.git ~/price-check
```

## 2. Point Hermes at the skill
Add the repo's `skills` folder to `~/.hermes/config.yaml`:
```yaml
skills:
  external_dirs:
    - ~/price-check/skills
```
Restart Hermes (or the gateway), then check it is loaded:
```bash
hermes skills list | grep price-check
```
To update later: `cd ~/price-check && git pull`.

Alternative: copy instead of linking — `cp -r ~/price-check/skills/price-check ~/.hermes/skills/shopping/`.

## 3. Set the Telegram home channel
Cron results are delivered to the Telegram **home channel**. In your Telegram chat with the bot, send:
```
/sethome
```
(or set `TELEGRAM_HOME_CHANNEL` in `~/.hermes/.env`).

## 4. Track your first product
In Telegram, ask Hermes, e.g.:
```
Track the Ray-Ban Wayfarer RB2140 by model weekly, exclude case and lens
Track barcode 9300601234567 daily
Track "Phillips Avent Natural baby bottle 260ml 2 pack" fortnightly, max $40
```
You should get:
1. a confirmation with the cron job id, and
2. a 🆕 baseline message with the best 3 retailers and the price range.

Data is stored in `~/.hermes/data/price-check/`.

## 5. Verify
```bash
hermes cron list                 # the "price-check: <name>" job is there
hermes cron run <job_id>         # run now: should be silent (no Telegram message) if nothing moved
ls ~/.hermes/cron/output/        # silent runs are still saved here for checking
```
Simulate a price move: edit a `total` in `~/.hermes/data/price-check/snapshots/<slug>.json`, run the job again, and you should receive a 📉/📈 alert naming that retailer.

## Everyday use (in Telegram)
- "What products am I tracking?"
- "What's the price of the RB2140?"
- "Check the baby bottles now"
- "Change the Ray-Bans to daily" / "Pause the Ray-Bans" / "Stop tracking barcode 9300601234567"

## Troubleshooting
- **No messages at all:** check `/sethome` was set and `hermes cron list` shows the job active. Failed runs are always delivered, so silence usually means "no change".
- **False alerts or wrong totals:** look at the snapshot JSON and the run output in `~/.hermes/cron/output/`. If this keeps happening, that is the trigger for Phase 2 (a helper script that does filtering, maths and comparison exactly).
- **Missed retailers:** add them to `skills/price-check/references/retailers-au.md`, or track by barcode/model for tighter matches.
