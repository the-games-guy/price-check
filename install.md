# Install as a skill on Amy (ZORO, `assistant` profile)

Price Check runs as a skill on Amy's existing Hermes profile. It does **not** get its own profile, gateway, bot or login. It holds no credentials and touches no money, so a separate profile would add a gateway process, a 512–768 MB sandbox container and another OAuth grant on the N150, and isolate nothing.

Written against Hermes 0.20.4 on ZORO (CT100). Commands run from the **Proxmox host shell**. `Z` means "run as zoro inside CT100":

```bash
Z() { pct exec 100 -- su - zoro -c "$*"; }
```

Sandbox vs host paths (see `hermes-adding-external-services.md` §5a):

| | Host (ZORO) | Sandbox |
|---|---|---|
| Skill (read-only) | `/home/zoro/.hermes/profiles/assistant/skills/price-check/` | `/root/.hermes/skills/price-check/` |
| Data (read-write) | `/home/zoro/price-check-data/` | `/root/price-check-data/` |
| Repo clone | `/home/zoro/price-check/` | not mounted |

## 0. Pre-flight

```bash
Z "date"               # container clock should be Australia/Melbourne; cron times assume it
Z "hermes --version"
```

**Egress test.** This decides how much opening up is needed, so do it before anything else. The skill only works if Amy can open AU retailer pages. Check where her page fetching actually runs:

```bash
Z "hermes -p assistant chat -q 'Two tests, show raw results only. 1) With your web browsing or page-extract tool (NOT the terminal), open https://www.officeworks.com.au/ and report the page title or the exact error. 2) In the terminal run: curl -sS -o /dev/null -w \"%{http_code}\\n\" https://www.officeworks.com.au/ and show the raw output.' -Q"
```

| Result | Meaning | Action |
|---|---|---|
| Tool works, curl blocked | Page reading runs in the gateway, outside the sandbox allowlist | Nothing to open. Skip step 4. |
| Tool says "ddgs is a search-only backend and cannot extract URL content" | No extract backend is configured. **This was ZORO's result on 2026-10-13.** | Do step 0a, then rerun test 1 only. |
| Both blocked by the proxy | Page reading runs inside the sandbox | Step 4: add retailer domains to the global allowlist |
| Tool gets 403 / captcha / "access denied" | The retailer blocks bots | Expected for some stores (JB Hi-Fi, Big W, Kmart often do). The skill records them as `failed`. If most stores block, the skill isn't worth running in Phase 1. Stop and look at Phase 2's SerpApi source instead. |

A curl 403 (`CONNECT tunnel failed`) from the sandbox is the egress allowlist working as intended. Leave it closed; the skill doesn't use the terminal for fetching.

## 0a. Give Amy a page-extract backend (Firecrawl)

Amy's web search uses DuckDuckGo (`ddgs`), which can search but can't open pages. Keep search on ddgs (free) and use **Firecrawl** for extraction only.

**Tested on ZORO, 2026-10-13:**

| Backend | JB Hi-Fi | Big W |
|---|---|---|
| Tavily | Page loaded, but the price was empty because it's added by JavaScript | "Failed to fetch url" (blocked) |
| Firecrawl | $219 | $185 (special, was $219) |

Firecrawl renders the page in a browser, so it works for both stores. Its free tier is 1,000 credits/month at 1 credit per page. A check opens about 10–15 pages, so that's roughly 65–100 product checks a month. Keep most products weekly. A daily product uses around 300–450 credits a month on its own.

1. Sign up at firecrawl.dev and copy the API key.
2. Add the key to Amy's **profile** `.env`. Check first, never blind-append:
   ```bash
   Z "grep -q '^FIRECRAWL_API_KEY=' ~/.hermes/profiles/assistant/.env && echo PRESENT || echo safe"
   Z "printf '\nFIRECRAWL_API_KEY=%s\n' 'PASTE_KEY' >> ~/.hermes/profiles/assistant/.env && chmod 600 ~/.hermes/profiles/assistant/.env"
   ```
   Hermes treats this as a tool credential and keeps it out of the sandbox. Never add it to `docker_forward_env`.
3. Set the backends. This backs up the config first:
   ```bash
   Z "cp ~/.hermes/profiles/assistant/config.yaml ~/.hermes/profiles/assistant/config.yaml.bak-\$(date +%Y%m%d-%H%M) && hermes -p assistant config set web.search_backend ddgs && hermes -p assistant config set web.extract_backend firecrawl && grep -n -A4 '^web:' ~/.hermes/profiles/assistant/config.yaml"
   ```
4. Restart Amy's gateway (`hermes -p assistant gateway restart`), then start a fresh session and test a JavaScript-priced store and a bot-blocking one:
   ```bash
   Z "hermes -p assistant chat -q 'Open these two pages with web_extract and report raw: URL, product title, price shown, any error. Do not guess prices. https://www.jbhifi.com.au/products/apple-airpods-4 https://www.bigw.com.au/product/apple-airpods-4/p/245249' -Q"
   ```
   - Both prices showing means it works. Skip step 4; no retailer domains need opening.
   - A proxy or connection error naming `api.firecrawl.dev` means the gateway's calls also go through the egress proxy. Add it to the global `proxy.extra_allowed_hosts`, run `hermes egress setup --restart`, and test again.

If a store still blocks Firecrawl, the skill records it as `failed`. If that becomes common, Phase 2 adds Google Shopping (SerpApi) as a source.

## 1. Copy the skill in (no symlinks, no `external_dirs`)

```bash
Z "git clone https://github.com/the-games-guy/price-check.git ~/price-check"
Z "cp -r ~/price-check/skills/price-check ~/.hermes/profiles/assistant/skills/"
Z "find ~/.hermes/profiles/assistant/skills -type l"     # must print nothing (2026-09-28 rule)
Z "python3 ~/.hermes/profiles/assistant/skills/price-check/scripts/price_check.py --help | head -3"
```

- **Why not a symlink:** any symlink inside `skills/` makes Hermes mount a `/tmp` staging copy that gets deleted under the running container. That's the 28 Sep "skills/ is empty" bug.
- **Why not `skills.external_dirs`:** extra skill directories load into the gateway, but they aren't mounted into the sandbox, so the script would be missing at `/root/.hermes/skills/...`.

To update later:
```bash
Z "cd ~/price-check && git pull && rm -rf ~/.hermes/profiles/assistant/skills/price-check && cp -r ~/price-check/skills/price-check ~/.hermes/profiles/assistant/skills/"
```

## 2. Data folder and read-write bind

`/root/.hermes` is read-only in the sandbox, and `/root` itself only lasts as long as the container. State has to live on a host folder bound in read-write, the same pattern as `/root/vault` and `/root/invest/...`:

```bash
Z "mkdir -p ~/price-check-data/snapshots ~/price-check-data/work ~/price-check-data/logs && chmod 700 ~/price-check-data"
```

In `~/.hermes/profiles/assistant/config.yaml`, under `terminal:`, add one line to the existing `docker_volumes` list. Keep the entries that are already there:

```yaml
  docker_volumes:
    # ...existing tokvault / _memory entries stay as they are...
    - "/home/zoro/price-check-data:/root/price-check-data:rw"
```

## 3. Recreate Amy's container

`docker_volumes` is only read when a container is created:

```bash
Z "docker ps -a"                         # note Amy's container id(s); expect one, remove any duplicates too
Z "docker stop <id> && docker rm <id>"
Z "hermes -p assistant chat -q 'Load the google-workspace skill and the amy-notion-todos skill, then run: ls /root/price-check-data && touch /root/price-check-data/work/.write-test && echo WRITE_OK. Show raw stdout.' -Q"
```

The new container is created by the session that loads the credential skills. Without that, the Google and Notion mounts silently never attach (2026-09-10 / 09-28 addenda). Then check the mounts:

```bash
pct exec 100 -- bash -c "for C in \$(docker ps -q); do echo == \$C; docker inspect \$C --format '{{range .Mounts}}{{.Source}} -> {{.Destination}} (rw={{.RW}}){{println}}{{end}}'; done"
```

Expect `/home/zoro/price-check-data -> /root/price-check-data (rw=true)`, the skills mount from the real path (no `/tmp/hermes-skills-safe-*`), and `google_token.json` still `rw=false`.

## 4. Egress allowlist (only if the step 0 test said browsing runs in the sandbox)

The allowlist is **global**: every profile gains these hosts, including Ledger and Scout. They're public retail sites, so that's acceptable, but keep the list to stores you actually shop at. In `~/.hermes/config.yaml` (global), under `proxy.extra_allowed_hosts`:

```yaml
    - "*.officeworks.com.au"
    - "*.jbhifi.com.au"
    - "*.bigw.com.au"
    - "*.kmart.com.au"
    - "*.target.com.au"
    - "*.amazon.com.au"
    - "*.ebay.com.au"
    - "*.harveynorman.com.au"
    - "*.thegoodguys.com.au"
    - "*.babybunting.com.au"
    - "*.chemistwarehouse.com.au"
    - "*.myer.com.au"
    - "*.davidjones.com"
    - "*.sunglasshut.com"
    # add more from skills/price-check/references/retailers-au.md as needed
```

```bash
Z "hermes egress setup --restart"
Z "ls -la ~/.hermes/profiles/assistant/proxy"     # symlink to ~/.hermes/proxy must still resolve
```

Rerun the step 0 test. If `*.domain` doesn't match the bare domain on 0.20.4, add the bare domain as well.

## 5. Telegram delivery

Amy's existing cron jobs already deliver to Telegram, so the home channel is normally set. Check without printing values:

```bash
Z "grep -c '^TELEGRAM_HOME_CHANNEL=' ~/.hermes/profiles/assistant/.env"   # 1 = set
```

If it prints 0, send `/sethome` to Amy's bot in your chat with her.

## 6. Live test of the helper in the sandbox

Start a fresh session (old sessions replay stale tool results):

```bash
Z "hermes -p assistant chat -q 'Load the price-check skill and run: python3 /root/.hermes/skills/price-check/scripts/price_check.py list. Show raw stdout and exit code. Do not summarise.' -Q"
```

Expect `Not tracking any products yet.` and exit 0. An `[Errno 2]` means a mount problem. Go back to step 3 and **don't** let Amy offer to rewrite the script.

Timezone check (message times use Australia/Melbourne):
```bash
Z "hermes -p assistant chat -q 'Run: python3 -c \"import zoneinfo;print(zoneinfo.ZoneInfo(\\\"Australia/Melbourne\\\"))\"' -Q"
```

## 7. Track the first product (Telegram, to Amy)

```
Track the Ray-Ban Wayfarer RB2140 by model weekly, exclude case and lens
Track barcode 9300601234561 daily
Track "Philips Avent Natural baby bottle 260ml 2 pack" fortnightly, max $40
```

You should get a confirmation with the cron job id, then a 🆕 baseline message.

**Schedules** come from the helper as 5-field cron at 8am, with a per-product minute off the hour so jobs don't pile up:

| Cadence | Schedule (example) |
|---|---|
| daily | `50 8 * * *` |
| every other day | `50 8 */2 * *` (odd dates; the 31st and the 1st run back to back) |
| weekly | `50 8 * * 1` (Mondays) |
| fortnightly | `50 8 1,15 * *` (1st and 15th, so about every two weeks) |
| monthly | `50 8 1 * *` |

Plain cron is used instead of `every 2d` / `every 14d` because those interval forms aren't verified on 0.20.4.

**Model: scheduled checks run on Claude Haiku 5.5.** Hermes doesn't let the agent pick a job's model, so a host-side script pins it with `hermes cron edit <id> --model`:
- It reads `products.json` and only edits jobs it hasn't pinned yet.
- A new tracker, or a re-created job, is picked up automatically.
- The first baseline check (run in chat when you add a product) uses Amy's own model.

```bash
Z "python3 ~/price-check/host/pin_models.py --dry-run"     # shows the cron edit it would run
Z "python3 ~/price-check/host/pin_models.py"               # pins now
Z "hermes -p assistant cron list | grep -A10 'price-check:'"
```
Then add it to zoro's crontab so new trackers are pinned within the hour. Cron has a minimal PATH, so give it hermes's full path:
```bash
Z "which hermes"     # e.g. /home/zoro/.local/bin/hermes; use it below
Z "(crontab -l 2>/dev/null | grep -v pin_models; echo '7 * * * * python3 /home/zoro/price-check/host/pin_models.py --hermes /home/zoro/.local/bin/hermes >> /home/zoro/price-check-data/logs/pin-models.log 2>&1') | crontab - && crontab -l | grep pin_models"
```
To use a different model, pass `--model <id> --force` (or set `PRICE_CHECK_MODEL`). If Haiku misses retailers (more "⚠ not rechecked" lines, or ⚠️ no-results messages), switch back with `--model claude-sonnet-5-5 --force`.

**Cost:** each run opens 10–18 pages on Claude, billed to extra usage. A few weekly products cost little. Several daily products add up, so keep daily for things you're actively waiting to buy.

## 8. Verify

```bash
Z "hermes -p assistant cron list"                 # 'price-check: <name>' is there, bound to price-check
Z "hermes -p assistant cron run <job_id>; sleep 90; hermes -p assistant cron runs <job_id>"
```

A second run straight after the baseline should end in `[SILENT]`, with no Telegram message.

Simulate a price move host-side:
```bash
Z "nano ~/price-check-data/snapshots/<slug>.json"   # change the first offer's "total" (e.g. +10)
Z "hermes -p assistant cron run <job_id>"
```
You should get a 📉 alert naming that retailer, "$X+10 → $X".

Then ask Amy "what am I tracking?".

Host-side runs of the helper (diagnostics) need the data path set, because the default is the sandbox path:
```bash
Z "PRICE_CHECK_HOME=~/price-check-data python3 ~/.hermes/profiles/assistant/skills/price-check/scripts/price_check.py list"
Z "cat ~/price-check-data/logs/<slug>.last.txt"      # why offers were dropped in the last run
```

## Everyday use (Telegram, to Amy)
- "What am I tracking?" / "What's the price of the RB2140?"
- "Check the baby bottles now" (replies even if nothing moved)
- "Change the Ray-Bans to daily" / "Pause the Ray-Bans" / "Stop tracking barcode 9300601234561"
- "How much is X right now?" for an untracked item: a one-off check, nothing saved

## Troubleshooting
- **No messages at all:** silence normally means "no change". Check `cron list` shows the job active and look at the cron output folder (`~/.hermes/profiles/assistant/cron/output/`, or `~/.hermes/cron/output/` on some versions). Failed runs are always delivered.
- **⚠️ no results every run:** read `logs/<slug>.last.txt`. If it's all `failed`, retailers are blocked or the egress list is missing them (step 0/4). If it's all "not confirmed on page", the search type is too strict. Try `name` with include keywords.
- **"⚠ not rechecked" lines:** that retailer's page didn't load. After 3 runs it's dropped and reported.
- **Amy says a file is missing, wiped or broken:** treat it as a hypothesis. Check host-side (`ls -la ~/price-check-data`) and the mount table (step 3) before acting.
- **Odd alerts:** every alert line names the retailer and old → new total, and every URL was opened in that run. Compare with the log, then fix the product filters with "change the Ray-Bans to exclude …".

## Tests (on any machine)
```bash
python3 -m unittest discover -s tests -v
```
