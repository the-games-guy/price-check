#!/usr/bin/env python3
"""price-check helper: the deterministic half of the price-check skill.

The agent finds retailer pages and reads prices off them. This script does
everything that must be exact and repeatable:

  * products.json management (add / update / pause / resume / remove)
  * cadence -> cron schedule
  * filtering offers (new only, AUD, identifiers, include/exclude, min/max)
  * one offer per retailer, ranking, top 3 and range
  * comparing with the last snapshot, carrying forward pages that could not
    be checked, and deciding whether anything moved
  * formatting every Telegram message

Python standard library only. Data lives in $PRICE_CHECK_HOME
(default /root/price-check-data, the sandbox side of a docker_volumes bind).

Exit codes: 0 ok, 2 bad input, 3 unknown product, 4 no qualifying offers.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import sys
import tempfile
import zlib
from pathlib import Path
from urllib.parse import urlparse

try:
    import fcntl  # Linux / macOS
except ImportError:  # pragma: no cover
    fcntl = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

VERSION = 1
SCRIPT_PATH = "/root/.hermes/skills/price-check/scripts/price_check.py"

EXIT_OK, EXIT_INPUT, EXIT_UNKNOWN, EXIT_NO_RESULTS = 0, 2, 3, 4

CADENCES = {
    "daily": "daily",
    "every_other_day": "every other day",
    "weekly": "weekly (Mondays)",
    "fortnightly": "fortnightly (1st and 15th)",
    "monthly": "monthly (1st)",
}
CADENCE_ALIASES = {
    "every other day": "every_other_day",
    "every-other-day": "every_other_day",
    "every 2 days": "every_other_day",
    "fortnight": "fortnightly",
    "biweekly": "fortnightly",
    "week": "weekly",
    "day": "daily",
    "month": "monthly",
}
SEARCH_TYPES = ("name", "model", "sku", "barcode")
STALE_LIMIT = 3

# Canonical retailer names by domain (keep in sync with references/retailers-au.md).
RETAILERS = {
    "amazon.com.au": "Amazon AU",
    "bigw.com.au": "Big W",
    "kmart.com.au": "Kmart",
    "target.com.au": "Target",
    "myer.com.au": "Myer",
    "davidjones.com": "David Jones",
    "catch.com.au": "Catch",
    "kogan.com": "Kogan",
    "ebay.com.au": "eBay",
    "jbhifi.com.au": "JB Hi-Fi",
    "harveynorman.com.au": "Harvey Norman",
    "thegoodguys.com.au": "The Good Guys",
    "officeworks.com.au": "Officeworks",
    "binglee.com.au": "Bing Lee",
    "apple.com": "Apple Store AU",
    "mwave.com.au": "Mwave",
    "scorptec.com.au": "Scorptec",
    "umart.com.au": "Umart",
    "ple.com.au": "PLE Computers",
    "babybunting.com.au": "Baby Bunting",
    "babykingdom.com.au": "Baby Kingdom",
    "chemistwarehouse.com.au": "Chemist Warehouse",
    "priceline.com.au": "Priceline Pharmacy",
    "toysrus.com.au": 'Toys"R"Us AU',
    "sunglasshut.com": "Sunglass Hut",
    "opsm.com.au": "OPSM",
    "specsavers.com.au": "Specsavers",
    "theiconic.com.au": "The Iconic",
    "gluestore.com.au": "Glue Store",
    "surfstitch.com": "Surf Stitch",
    "generalpants.com.au": "General Pants Co.",
    "rebelsport.com.au": "Rebel",
    "bcf.com.au": "BCF",
    "anacondastores.com": "Anaconda",
    "kathmandu.com.au": "Kathmandu",
    "bunnings.com.au": "Bunnings",
    "templeandwebster.com.au": "Temple & Webster",
    "adairs.com.au": "Adairs",
}
# Marketplaces: every third-party seller is its own retailer.
MARKETPLACES = {
    "ebay.com.au": ("eBay", None),  # (prefix, name when sold by the platform)
    "amazon.com.au": ("Amazon AU", "Amazon AU"),
    "catch.com.au": ("Catch", "Catch"),
    "kogan.com": ("Kogan Marketplace", "Kogan"),
}
PLATFORM_SELLER_NAMES = {"", "amazon", "amazon au", "amazon.com.au", "amazon australia",
                         "catch", "catch.com.au", "kogan", "kogan.com", "kogan australia"}
COMPARISON_SITES = {"google.com", "google.com.au", "shopping.google.com", "staticice.com.au",
                    "pricehipster.com", "getprice.com.au", "shopbot.com.au", "pricespy.com.au",
                    "pricerunner.com", "ozbargain.com.au"}
FOREIGN_STORES = {"amazon.com", "amazon.co.uk", "ebay.com", "ebay.co.uk", "aliexpress.com",
                  "temu.com", "wish.com", "walmart.com", "bestbuy.com", "newegg.com"}
NOT_NEW = re.compile(
    r"\b(used|refurb\w*|renewed|pre[- ]?owned|open[- ]?box|ex[- ]?display|second[- ]?hand|"
    r"grade [abc]|b[- ]grade|seconds)\b", re.I)


# ----------------------------------------------------------------- utilities

class InputError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("PRICE_CHECK_HOME", "/root/price-check-data"))


def tz():
    name = os.environ.get("PRICE_CHECK_TZ", "Australia/Melbourne")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return dt.datetime.now().astimezone().tzinfo


def now() -> dt.datetime:
    fixed = os.environ.get("PRICE_CHECK_NOW")  # tests only
    if fixed:
        return dt.datetime.fromisoformat(fixed)
    return dt.datetime.now(tz()).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.isoformat()


def nice_time(s: str | None) -> str:
    if not s:
        return "never"
    t = dt.datetime.fromisoformat(s)
    hour = t.hour % 12 or 12
    return f"{t:%a} {t.day} {t:%b} {hour}:{t:%M}{'am' if t.hour < 12 else 'pm'}"


def nice_date(s: str | None) -> str:
    if not s:
        return "never"
    t = dt.datetime.fromisoformat(s)
    return f"{t.day} {t:%b}"


def to_cents(value, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InputError(f"{field}: not a number")
    if isinstance(value, str):
        value = value.strip().replace("$", "").replace(",", "")
        if value.lower() in ("", "free"):
            return 0 if value.lower() == "free" else None
    try:
        cents = round(float(value) * 100)
    except (TypeError, ValueError):
        raise InputError(f"{field}: not a number: {value!r}")
    if cents < 0:
        raise InputError(f"{field}: negative")
    return cents


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def cents_to_num(cents: int | None):
    return None if cents is None else round(cents / 100, 2)


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", (s or "").lower())).strip()


def keyword_in(keyword: str, text: str) -> bool:
    """Whole-word match (plural s/es allowed). Keywords with digits also match with
    spaces and punctuation ignored, so '260ml' matches '260 mL' and '2-pack' matches '2 pack'."""
    k, t = norm_text(keyword), norm_text(text)
    if not k:
        return False
    if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?:e?s)?(?![a-z0-9])", t):
        return True
    return any(c.isdigit() for c in k) and norm_id(k) in norm_id(t)


def gtin_valid(code: str) -> bool:
    if not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", code):
        return False
    digits = [int(c) for c in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def gtin14(code: str) -> str:
    return re.sub(r"\D", "", code or "").zfill(14)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return s or "product"


def host_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    for prefix in ("www.", "m.", "shop."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def domain_match(host: str, domains) -> str | None:
    for d in domains:
        if host == d or host.endswith("." + d):
            return d
    return None


def parse_cadence(value: str) -> str:
    v = (value or "").strip().lower()
    v = CADENCE_ALIASES.get(v, v).replace(" ", "_").replace("-", "_")
    if v not in CADENCES:
        raise InputError(f"cadence must be one of: {', '.join(CADENCES)}")
    return v


def schedule_for(slug: str, cadence: str) -> str:
    """5-field cron. Minute is spread per product so jobs don't pile up on :00."""
    minute = 5 + zlib.crc32(slug.encode()) % 50
    if minute == 30:
        minute = 31
    hour = int(os.environ.get("PRICE_CHECK_HOUR", "8"))
    return {
        "daily": f"{minute} {hour} * * *",
        "every_other_day": f"{minute} {hour} */2 * *",
        "weekly": f"{minute} {hour} * * 1",
        "fortnightly": f"{minute} {hour} 1,15 * *",
        "monthly": f"{minute} {hour} 1 * *",
    }[cadence]


def cron_prompt(slug: str) -> str:
    return (f'Run the price-check skill\'s Procedure B for product slug "{slug}". '
            "Follow the skill's hard rules. Your final reply must be only the stdout "
            "of the commit command, verbatim.")


def split_list(values) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out.extend(x.strip() for x in v.split(",") if x.strip())
    return out


# ----------------------------------------------------------------- storage

@contextlib.contextmanager
def locked():
    base = home()
    (base / "snapshots").mkdir(parents=True, exist_ok=True)
    (base / "work").mkdir(exist_ok=True)
    (base / "logs").mkdir(exist_ok=True)
    with open(base / ".lock", "w") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield base
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


def read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_products() -> dict:
    data = read_json(home() / "products.json", {"version": VERSION, "products": []})
    data.setdefault("products", [])
    return data


def save_products(data: dict) -> None:
    write_json(home() / "products.json", data)


def find_product(data: dict, slug: str) -> dict:
    for p in data["products"]:
        if p["slug"] == slug:
            return p
    raise LookupError(slug)


def snapshot_path(slug: str) -> Path:
    return home() / "snapshots" / f"{slug}.json"


# ----------------------------------------------------------------- offers

def retailer_identity(offer: dict) -> tuple[str, str]:
    """Return (key, display name). Key is stable across runs: domain[|seller]."""
    url = offer.get("url") or ""
    host = host_of(url)
    if not host:
        raise InputError("missing or invalid url")
    if domain_match(host, COMPARISON_SITES):
        raise InputError("comparison site, not a retailer (open the retailer's own page)")
    if domain_match(host, FOREIGN_STORES):
        raise InputError("overseas store")
    market = domain_match(host, MARKETPLACES)
    if market:
        prefix, platform_name = MARKETPLACES[market]
        seller = (offer.get("seller") or "").strip()
        if seller.lower() in PLATFORM_SELLER_NAMES and platform_name:
            return market, platform_name
        if not seller or seller.lower() in PLATFORM_SELLER_NAMES:
            raise InputError(f"{prefix} listing needs the seller name in 'seller'")
        return f"{market}|{seller.lower()}", f"{prefix} – {seller}"
    known = domain_match(host, RETAILERS)
    if known:
        return known, RETAILERS[known]
    name = (offer.get("retailer") or "").strip() or host
    return host, name


def check_offer(raw: dict, product: dict) -> dict:
    """Validate one observed offer against the product. Raises InputError with a reason."""
    if not isinstance(raw, dict):
        raise InputError("offer is not an object")
    key, name = retailer_identity(raw)
    title = (raw.get("title") or "").strip()
    if not title:
        raise InputError("missing title")
    currency = (raw.get("currency") or "AUD").upper()
    if currency != "AUD":
        raise InputError(f"currency {currency}, AUD only")
    condition = (raw.get("condition") or "new").lower()
    if condition != "new" or NOT_NEW.search(title):
        raise InputError("not new")
    price = to_cents(raw.get("price"), "price")
    if not price:
        raise InputError("missing price")
    if price > 100_000_00:
        raise InputError("price implausibly high")
    delivery = to_cents(raw.get("delivery"), "delivery")
    total = price + (delivery or 0)

    for kw in product.get("exclude", []):
        if keyword_in(kw, title):
            raise InputError(f"title contains excluded keyword '{kw}'")
    for kw in product.get("include", []):
        if not keyword_in(kw, title):
            raise InputError(f"title missing include keyword '{kw}'")

    st, query = product["search_type"], product["query"]
    seen = raw.get("id_on_page") is True
    if st == "barcode":
        gtin = raw.get("gtin")
        if gtin and gtin14(str(gtin)) != gtin14(query):
            raise InputError(f"barcode on page {gtin} does not match {query}")
        if not (seen or (gtin and gtin14(str(gtin)) == gtin14(query))):
            raise InputError("barcode not confirmed on page (set id_on_page or gtin)")
    elif st in ("model", "sku"):
        q = norm_id(query)
        mpn = norm_id(str(raw.get("mpn") or ""))
        if mpn and q not in mpn and mpn not in q:
            raise InputError(f"model on page {raw.get('mpn')} does not match {query}")
        if not (seen or q in norm_id(title) or (mpn and q in mpn)):
            raise InputError(f"{st} {query} not confirmed on page (set id_on_page)")

    if product.get("min_price") is not None and total < to_cents(product["min_price"], "min"):
        raise InputError(f"total {money(total)} below min_price")
    if product.get("max_price") is not None and total > to_cents(product["max_price"], "max"):
        raise InputError(f"total {money(total)} above max_price")

    return {"key": key, "retailer": name, "title": title, "url": raw["url"],
            "price": price, "delivery": delivery, "total": total,
            "stale": False, "stale_runs": 0}


def offer_out(o: dict) -> dict:
    return {"key": o["key"], "retailer": o["retailer"], "title": o["title"], "url": o["url"],
            "price": cents_to_num(o["price"]), "delivery": cents_to_num(o["delivery"]),
            "total": cents_to_num(o["total"]), "stale": o["stale"], "stale_runs": o["stale_runs"]}


def offer_in(o: dict) -> dict:
    return {"key": o.get("key") or retailer_key_fallback(o), "retailer": o["retailer"],
            "title": o.get("title", ""), "url": o["url"],
            "price": to_cents(o.get("price"), "price") or 0,
            "delivery": to_cents(o.get("delivery"), "delivery"),
            "total": to_cents(o.get("total"), "total") or 0,
            "stale": bool(o.get("stale")), "stale_runs": int(o.get("stale_runs") or 0)}


def retailer_key_fallback(o: dict) -> str:
    try:
        return retailer_identity(o)[0]
    except InputError:
        return host_of(o.get("url", "")) or o.get("retailer", "?")


def unavailable_key(u: dict) -> tuple[str, str]:
    try:
        return retailer_identity(u)
    except InputError:
        host = host_of(u.get("url", ""))
        return host or (u.get("retailer") or "?"), u.get("retailer") or host or "?"


def read_observations(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise InputError(f"offers file not found: {path}")
    except json.JSONDecodeError as e:
        raise InputError(f"offers file is not valid JSON: {e}")
    if isinstance(data, list):
        data = {"offers": data}
    if not isinstance(data, dict):
        raise InputError("offers file must be an object with an 'offers' list")
    for k in ("offers", "unavailable", "failed"):
        data.setdefault(k, [])
        if not isinstance(data[k], list):
            raise InputError(f"'{k}' must be a list")
    return data


def evaluate(product: dict, obs: dict, previous: dict | None):
    """Core of a run. Returns (result dict, notes list). No I/O."""
    notes: list[str] = []
    fresh: dict[str, dict] = {}
    rejected: dict[str, str] = {}

    out_of_stock = []
    for raw in obs["offers"]:
        if isinstance(raw, dict) and raw.get("in_stock") is False:
            out_of_stock.append(dict(raw, reason=raw.get("reason") or "out of stock"))
            continue
        try:
            o = check_offer(raw, product)
        except InputError as e:
            label = (raw.get("retailer") if isinstance(raw, dict) else None) or \
                (host_of(raw.get("url", "")) if isinstance(raw, dict) else "?")
            notes.append(f"dropped {label}: {e}")
            if isinstance(raw, dict):
                try:
                    rejected[retailer_identity(raw)[0]] = str(e)
                except InputError:
                    pass
            continue
        best = fresh.get(o["key"])
        if best is None or o["total"] < best["total"]:
            fresh[o["key"]] = o

    unavailable: dict[str, dict] = {}
    for u in obs["unavailable"] + out_of_stock:
        if not isinstance(u, dict) or not u.get("url"):
            notes.append("ignored unavailable entry without url")
            continue
        key, name = unavailable_key(u)
        if key in fresh:
            continue  # another listing at this retailer qualified
        unavailable[key] = {"key": key, "retailer": name, "url": u["url"],
                            "reason": (u.get("reason") or "unavailable").strip(), "missed_runs": 0}

    prev_offers = [offer_in(o) for o in (previous or {}).get("offers", [])]
    prev_by_key = {o["key"]: o for o in prev_offers}
    stale_dropped: list[dict] = []
    offers = dict(fresh)
    for key, old in prev_by_key.items():
        if key in offers or key in unavailable or key in rejected:
            continue
        runs = old["stale_runs"] + 1
        if runs >= STALE_LIMIT:
            stale_dropped.append(old)
            notes.append(f"dropped {old['retailer']}: not rechecked for {STALE_LIMIT} runs")
            continue
        carried = dict(old, stale=True, stale_runs=runs)
        offers[key] = carried
        notes.append(f"carried forward {old['retailer']} (not rechecked, run {runs})")

    for u in (previous or {}).get("unavailable", []):
        key = u.get("key") or unavailable_key(u)[0]
        if key in offers or key in unavailable or key in rejected:
            continue
        missed = int(u.get("missed_runs") or 0) + 1
        if missed < STALE_LIMIT:
            unavailable[key] = dict(u, key=key, missed_runs=missed)

    ranked = sorted(offers.values(), key=lambda o: (o["total"], o["retailer"].lower()))
    result = {
        "fresh": len(fresh),
        "offers": ranked,
        "unavailable": sorted(unavailable.values(), key=lambda u: u["retailer"].lower()),
        "top3": [o["key"] for o in ranked[:3]],
        "range": ({"low": ranked[0]["total"], "high": ranked[-1]["total"], "retailers": len(ranked)}
                  if ranked else None),
        "rejected": rejected,
        "stale_dropped": stale_dropped,
    }
    result["changes"] = diff(previous, result, prev_by_key) if previous else None
    return result, notes


def previous_top3(previous: dict, prev_by_key: dict) -> list[str]:
    """Top-3 keys of the last snapshot. Falls back to ranking its offers, which also
    covers older snapshots that stored retailer names instead of keys."""
    keys = [k for k in previous.get("top3", []) if k in prev_by_key]
    if len(keys) == min(3, len(prev_by_key)):
        return keys
    return [o["key"] for o in sorted(prev_by_key.values(), key=lambda o: o["total"])[:3]]


def diff(previous: dict, result: dict, prev_by_key: dict) -> list[str]:
    new_by_key = {o["key"]: o for o in result["offers"]}
    old_top = previous_top3(previous, prev_by_key)
    new_top = result["top3"]
    unavailable = {u["key"]: u for u in result["unavailable"]}
    lines: list[str] = []

    for key in new_top:
        o = new_by_key[key]
        old = prev_by_key.get(key)
        if key in old_top and old:
            d = o["total"] - old["total"]
            if d:
                arrow = "↓" if d < 0 else "↑"
                lines.append(f"• {o['retailer']}: {money(old['total'])} → {money(o['total'])} "
                             f"({arrow}{money(abs(d))})")
        else:
            was = f" (was {money(old['total'])})" if old and old["total"] != o["total"] else ""
            lines.append(f"• {o['retailer']} entered the top 3 at {money(o['total'])}{was}")

    dropped = {o["key"] for o in result["stale_dropped"]}
    for key in old_top:
        if key in new_top:
            continue
        old = prev_by_key[key]
        if key in new_by_key:
            why = f"now {money(new_by_key[key]['total'])}"
        elif key in unavailable:
            why = unavailable[key]["reason"]
        elif key in result["rejected"]:
            why = f"no longer matches: {result['rejected'][key]}"
        elif key in dropped:
            why = f"could not be checked for {STALE_LIMIT} runs"
        else:
            why = "listing gone"
        lines.append(f"• {old['retailer']} left the top 3 ({why})")

    for o in result["stale_dropped"]:
        if o["key"] not in old_top:
            lines.append(f"• {o['retailer']} could not be checked for {STALE_LIMIT} runs (removed)")

    old_high = max((o["total"] for o in prev_by_key.values()), default=None)
    new_high = result["range"]["high"] if result["range"] else None
    if old_high is not None and new_high is not None and old_high != new_high:
        lines.append(f"• Range high: {money(old_high)} → {money(new_high)}")
    return lines


# ----------------------------------------------------------------- messages

def delivery_label(cents: int | None) -> str:
    if cents is None:
        return "+ del?"
    if cents == 0:
        return "free del"
    return f"+ {money(cents)} del"


def offer_line(i: int, o: dict, arrow: str = "") -> str:
    stale = " ⚠ not rechecked" if o.get("stale") else ""
    tail = f" {arrow}" if arrow else ""
    return f"{i}. {o['retailer']} — {money(o['total'])} ({delivery_label(o['delivery'])}){tail}{stale}\n{o['url']}"


def range_line(rng: dict, with_count: bool = True) -> str:
    span = money(rng["low"]) if rng["low"] == rng["high"] else f"{money(rng['low'])} – {money(rng['high'])}"
    if not with_count:
        return f"Range: {span}"
    n = rng["retailers"]
    return f"Range: {span} across {n} retailer{'s' if n != 1 else ''}"


def msg_baseline(product: dict, result: dict) -> str:
    top = result["offers"][:3]
    n = result["range"]["retailers"]
    head = (f"Best {len(top)} of {n} AU retailers:" if n > 1 else "Only 1 AU retailer found:")
    lines = [f"🆕 Now tracking: {product['name']}", head, ""]
    lines += [offer_line(i, o) for i, o in enumerate(top, 1)]
    lines += ["", range_line(result["range"], with_count=False),
              f"Checking {CADENCES[product['cadence']]}. I'll only message you when a price moves."]
    return "\n".join(lines)


def msg_change(product: dict, result: dict, previous: dict) -> str:
    prev = {o["key"]: offer_in(o) for o in previous.get("offers", [])}
    old_low = min((o["total"] for o in prev.values()), default=None)
    new_low = result["range"]["low"]
    if old_low is None or new_low == old_low:
        head = f"🔄 {product['name']} — best still {money(new_low)}"
    else:
        icon = "📉" if new_low < old_low else "📈"
        head = f"{icon} {product['name']} — best now {money(new_low)} (was {money(old_low)})"
    old_top = set(previous_top3(previous, prev))
    lines = [head, "", "What changed:", *result["changes"], "", "Best 3 now:"]
    for i, o in enumerate(result["offers"][:3], 1):
        old = prev.get(o["key"])
        if o["key"] not in old_top or not old:
            arrow = "new"
        else:
            arrow = "↓" if o["total"] < old["total"] else "↑" if o["total"] > old["total"] else "="
        lines.append(offer_line(i, o, arrow))
    lines += ["", range_line(result["range"])]
    return "\n".join(lines)


def msg_current(product: dict, snap: dict, header: str | None = None) -> str:
    offers = [offer_in(o) for o in snap.get("offers", [])]
    if not offers:
        return f"{product['name']}: no qualifying AU offers found yet."
    lines = [header or f"{product['name']} — as of {nice_time(snap.get('checked_at'))}"]
    lines += [offer_line(i, o) for i, o in enumerate(offers[:3], 1)]
    rng = {"low": offers[0]["total"], "high": max(o["total"] for o in offers), "retailers": len(offers)}
    lines.append(range_line(rng))
    return "\n".join(lines)


def msg_no_results(product: dict, previous: dict | None) -> str:
    if previous and previous.get("offers"):
        return (f"⚠️ {product['name']}: no qualifying AU offers found this run.\n"
                f"Kept the previous result from {nice_time(previous.get('checked_at'))}. "
                "The search may need adjusting (try a model number or barcode), "
                "retailer pages may be blocked, or the product may be discontinued.")
    return (f"⚠️ {product['name']}: no qualifying AU offers found, so nothing is saved yet.\n"
            "Try a model number or barcode, or loosen the include/exclude keywords.")


def snapshot_doc(product: dict, result: dict, checked_at: str) -> dict:
    return {
        "version": VERSION,
        "slug": product["slug"],
        "checked_at": checked_at,
        "offers": [offer_out(o) for o in result["offers"]],
        "unavailable": result["unavailable"],
        "top3": result["top3"],
        "range": ({"low": cents_to_num(result["range"]["low"]),
                   "high": cents_to_num(result["range"]["high"]),
                   "retailers": result["range"]["retailers"]} if result["range"] else None),
    }


# ----------------------------------------------------------------- commands

def product_from_args(a, slug: str = "") -> dict:
    st = a.type
    query = (a.query or "").strip()
    if not query:
        raise InputError("query is required")
    if st == "barcode":
        query = re.sub(r"[\s-]", "", query)
        if not gtin_valid(query):
            raise InputError(f"barcode {query} is not a valid EAN-8/UPC-A/EAN-13/GTIN-14 "
                             "(wrong length or check digit, likely a typo)")
    p = {
        "slug": slug,
        "name": (a.name or query).strip(),
        "search_type": st,
        "query": query,
        "include": split_list(a.include),
        "exclude": split_list(a.exclude),
        "min_price": a.min,
        "max_price": a.max,
        "cadence": parse_cadence(a.cadence) if getattr(a, "cadence", None) else "weekly",
    }
    if p["min_price"] is not None and p["max_price"] is not None and p["min_price"] > p["max_price"]:
        raise InputError("min price is above max price")
    return p


def cmd_add(a) -> int:
    with locked():
        data = load_products()
        p = product_from_args(a)
        base = slugify(a.slug or p["name"])
        taken = {x["slug"] for x in data["products"]}
        slug, n = base, 2
        while slug in taken:
            suffix = f"-{n}"
            slug, n = base[: 40 - len(suffix)] + suffix, n + 1
        p.update(slug=slug, cron_job_id=None, active=True, created_at=iso(now()), last_checked=None)
        data["products"].append(p)
        save_products(data)
    warn = None
    if p["search_type"] == "sku":
        warn = "Retailer SKUs rarely match across stores; a model number or barcode works better."
    out = {"slug": slug, "schedule": schedule_for(slug, p["cadence"]),
           "cadence": CADENCES[p["cadence"]], "job_name": f"price-check: {p['name']}",
           "prompt": cron_prompt(slug), "warning": warn}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_set_job(a) -> int:
    with locked():
        data = load_products()
        p = find_product(data, a.slug)
        p["cron_job_id"] = a.job_id
        save_products(data)
    print(json.dumps({"slug": a.slug, "cron_job_id": a.job_id}))
    return EXIT_OK


def cmd_update(a) -> int:
    with locked():
        data = load_products()
        p = find_product(data, a.slug)
        changed, reset = [], False
        if a.name:
            p["name"] = a.name.strip(); changed.append("name")
        if a.cadence:
            p["cadence"] = parse_cadence(a.cadence); changed.append("cadence")
        if a.type or a.query:
            merged = argparse.Namespace(type=a.type or p["search_type"], query=a.query or p["query"],
                                        name=p["name"], include=None, exclude=None, min=None,
                                        max=None, cadence=p["cadence"])
            q = product_from_args(merged)
            p["search_type"], p["query"] = q["search_type"], q["query"]
            changed.append("search"); reset = True
        if a.include is not None:
            p["include"] = split_list(a.include); changed.append("include"); reset = True
        if a.exclude is not None:
            p["exclude"] = split_list(a.exclude); changed.append("exclude"); reset = True
        if a.min is not None or a.clear_min:
            p["min_price"] = None if a.clear_min else a.min; changed.append("min_price"); reset = True
        if a.max is not None or a.clear_max:
            p["max_price"] = None if a.clear_max else a.max; changed.append("max_price"); reset = True
        if p["min_price"] is not None and p["max_price"] is not None and p["min_price"] > p["max_price"]:
            raise InputError("min price is above max price")
        if not changed:
            raise InputError("nothing to update")
        save_products(data)
        if reset and snapshot_path(p["slug"]).exists():
            snapshot_path(p["slug"]).unlink()
    out = {"slug": p["slug"], "changed": changed, "reset_baseline": reset,
           "cron_job_id": p.get("cron_job_id")}
    if "cadence" in changed:
        out["schedule"] = schedule_for(p["slug"], p["cadence"])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


def cmd_active(a, active: bool) -> int:
    with locked():
        data = load_products()
        p = find_product(data, a.slug)
        p["active"] = active
        save_products(data)
    print(json.dumps({"slug": p["slug"], "active": active, "cron_job_id": p.get("cron_job_id"),
                      "cron_action": "resume" if active else "pause"}))
    return EXIT_OK


def cmd_remove(a) -> int:
    with locked():
        data = load_products()
        p = find_product(data, a.slug)
        data["products"] = [x for x in data["products"] if x["slug"] != a.slug]
        save_products(data)
        if snapshot_path(a.slug).exists():
            snapshot_path(a.slug).unlink()
    print(json.dumps({"removed": a.slug, "cron_job_id": p.get("cron_job_id"),
                      "job_name": f"price-check: {p['name']}"}))
    return EXIT_OK


def cmd_find(a) -> int:
    data = load_products()
    q, qid = a.text.lower(), norm_id(a.text)
    hits = [p for p in data["products"]
            if q in p["name"].lower() or q in p["slug"]
            or (qid and (qid in norm_id(p["query"]) or norm_id(p["query"]) in qid))
            or (qid and qid in norm_id(p["name"]))]
    print(json.dumps([{"slug": p["slug"], "name": p["name"], "search_type": p["search_type"],
                       "query": p["query"], "active": p["active"]} for p in hits], indent=2,
                     ensure_ascii=False))
    return EXIT_OK


def cmd_list(a) -> int:
    data = load_products()
    ps = data["products"]
    if not ps:
        print("Not tracking any products yet.")
        return EXIT_OK
    lines = [f"Tracking {len(ps)} product{'s' if len(ps) != 1 else ''}:", ""]
    for i, p in enumerate(ps, 1):
        paused = ", paused" if not p.get("active", True) else ""
        lines.append(f"{i}. {p['name']} — {p['search_type']} {p['query']} — "
                     f"{CADENCES[p['cadence']]}{paused}")
        snap = read_json(snapshot_path(p["slug"]), None)
        if snap and snap.get("offers"):
            best = offer_in(snap["offers"][0])
            lines.append(f"   Best: {money(best['total'])} at {best['retailer']} "
                         f"(checked {nice_date(snap.get('checked_at'))})")
        else:
            lines.append("   No result yet")
    print("\n".join(lines))
    return EXIT_OK


def cmd_show(a) -> int:
    data = load_products()
    p = find_product(data, a.slug)
    snap = read_json(snapshot_path(a.slug), None)
    if not snap:
        print(f"{p['name']}: not checked yet.")
        return EXIT_OK
    print(msg_current(p, snap))
    return EXIT_OK


def cmd_plan(a) -> int:
    data = load_products()
    p = find_product(data, a.slug)
    snap = read_json(snapshot_path(a.slug), None) or {}
    recheck = [{"retailer": o["retailer"], "url": o["url"], "last_total": o.get("total"),
                "was": "offer", "stale": o.get("stale", False)} for o in snap.get("offers", [])]
    recheck += [{"retailer": u["retailer"], "url": u["url"], "was": u.get("reason", "unavailable")}
                for u in snap.get("unavailable", [])]
    offers_file = str(home() / "work" / f"{a.slug}.offers.json")
    out = {
        "product": {k: p.get(k) for k in ("slug", "name", "search_type", "query", "include",
                                          "exclude", "min_price", "max_price", "active")},
        "baseline": not snap,
        "recheck_first": recheck,
        "offers_file": offers_file,
        "commit": f"python3 {SCRIPT_PATH} commit {a.slug} --offers {offers_file}",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


def write_log(slug: str, notes: list[str], when: str) -> Path:
    path = home() / "logs" / f"{slug}.last.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{when}\n" + "\n".join(notes) + "\n", encoding="utf-8")
    return path


def cmd_commit(a) -> int:
    with locked():
        data = load_products()
        p = find_product(data, a.slug)
        if not p.get("active", True) and not a.always_message:
            print("[SILENT]")
            return EXIT_OK
        obs = read_observations(a.offers)
        previous = read_json(snapshot_path(a.slug), None)
        if previous is not None and not previous.get("offers"):
            previous = None  # nothing to compare with: treat as a baseline
        result, notes = evaluate(p, obs, previous)
        when = iso(now())
        if not a.dry_run:
            log = write_log(a.slug, notes, when)
            if notes:
                print(f"notes: {len(notes)} (see {log})", file=sys.stderr)

        if result["fresh"] == 0:
            print(msg_no_results(p, previous))
            return EXIT_NO_RESULTS

        if previous is None:
            message, changed = msg_baseline(p, result), True
        elif result["changes"]:
            message, changed = msg_change(p, result, previous), True
        else:
            message, changed = None, False

        if not a.dry_run:
            write_json(snapshot_path(a.slug), snapshot_doc(p, result, when))
            p["last_checked"] = when
            save_products(data)

    if message:
        print(message)
    elif a.always_message:
        since = nice_time(previous.get("checked_at")) if previous else "the last check"
        print(msg_current(p, snapshot_doc(p, result, when),
                          header=f"No change since {since}. {p['name']} — now:"))
    else:
        print("[SILENT]")
    return EXIT_OK


def cmd_oneoff(a) -> int:
    p = product_from_args(a, slug="one-off")
    p["cadence"] = "weekly"
    obs = read_observations(a.offers)
    result, notes = evaluate(p, obs, None)
    if notes:
        print("notes:\n  " + "\n  ".join(notes), file=sys.stderr)
    if not result["fresh"]:
        print(f"⚠️ {p['name']}: no qualifying AU offers found.")
        return EXIT_NO_RESULTS
    snap = snapshot_doc(p, result, iso(now()))
    print(msg_current(p, snap, header=f"{p['name']} — one-off check (not tracked)"))
    return EXIT_OK


def cmd_schedule(a) -> int:
    cadence = parse_cadence(a.cadence)
    print(schedule_for(a.slug, cadence))
    return EXIT_OK


# ----------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="price_check.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def product_args(sp, required=True):
        sp.add_argument("--name")
        sp.add_argument("--type", choices=SEARCH_TYPES, required=required)
        sp.add_argument("--query", required=required)
        sp.add_argument("--include", action="append", help="repeat or comma-separate")
        sp.add_argument("--exclude", action="append", help="repeat or comma-separate")
        sp.add_argument("--min", type=float)
        sp.add_argument("--max", type=float)

    sp = sub.add_parser("add", help="track a new product")
    product_args(sp)
    sp.add_argument("--cadence", default="weekly")
    sp.add_argument("--slug", help="optional slug override")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("set-job", help="record the cron job id")
    sp.add_argument("slug"); sp.add_argument("job_id")
    sp.set_defaults(fn=cmd_set_job)

    sp = sub.add_parser("update", help="change cadence, name, search or filters")
    sp.add_argument("slug")
    sp.add_argument("--name"); sp.add_argument("--cadence")
    sp.add_argument("--type", choices=SEARCH_TYPES); sp.add_argument("--query")
    sp.add_argument("--include", action="append"); sp.add_argument("--exclude", action="append")
    sp.add_argument("--min", type=float); sp.add_argument("--max", type=float)
    sp.add_argument("--clear-min", action="store_true"); sp.add_argument("--clear-max", action="store_true")
    sp.set_defaults(fn=cmd_update)

    for name, active in (("pause", False), ("resume", True)):
        sp = sub.add_parser(name)
        sp.add_argument("slug")
        sp.set_defaults(fn=lambda a, active=active: cmd_active(a, active))

    sp = sub.add_parser("remove"); sp.add_argument("slug"); sp.set_defaults(fn=cmd_remove)
    sp = sub.add_parser("find", help="match free text to tracked products")
    sp.add_argument("text"); sp.set_defaults(fn=cmd_find)
    sp = sub.add_parser("list"); sp.set_defaults(fn=cmd_list)
    sp = sub.add_parser("show"); sp.add_argument("slug"); sp.set_defaults(fn=cmd_show)
    sp = sub.add_parser("plan", help="what to recheck and where to write offers")
    sp.add_argument("slug"); sp.set_defaults(fn=cmd_plan)

    sp = sub.add_parser("commit", help="evaluate observed offers, save, print the reply")
    sp.add_argument("slug")
    sp.add_argument("--offers", required=True)
    sp.add_argument("--always-message", action="store_true",
                    help="print the current result even when nothing changed")
    sp.add_argument("--dry-run", action="store_true", help="evaluate without writing files")
    sp.set_defaults(fn=cmd_commit)

    sp = sub.add_parser("oneoff", help="evaluate offers for an untracked product, no writes")
    product_args(sp)
    sp.add_argument("--offers", required=True)
    sp.set_defaults(fn=cmd_oneoff)

    sp = sub.add_parser("schedule", help="cron schedule for a slug and cadence")
    sp.add_argument("slug"); sp.add_argument("cadence")
    sp.set_defaults(fn=cmd_schedule)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_INPUT
    except LookupError as e:
        print(f"error: no tracked product with slug {e}. Run 'list' or 'find'.", file=sys.stderr)
        return EXIT_UNKNOWN


if __name__ == "__main__":
    sys.exit(main())
