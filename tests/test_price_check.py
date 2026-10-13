"""Tests for skills/price-check/scripts/price_check.py.

Standard library only:  python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "price-check" / "scripts"))
import price_check as pc  # noqa: E402

BAN = "https://www.sunglasshut.com/au/rayban/rb2140-901"
DJ = "https://www.davidjones.com/rb2140"
EBAY = "https://www.ebay.com.au/itm/123"
ICONIC = "https://www.theiconic.com.au/rb2140"
MYER = "https://www.myer.com.au/p/rb2140"


def offer(url, price, delivery=0, title="Ray-Ban RB2140 Original Wayfarer Black", **kw):
    return dict(url=url, title=title, price=price, delivery=delivery, **kw)


class CLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        os.environ["PRICE_CHECK_HOME"] = str(self.home)
        os.environ["PRICE_CHECK_NOW"] = "2026-10-13T08:17:00+11:00"

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("PRICE_CHECK_NOW", None)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pc.main(list(argv))
        return code, out.getvalue().strip(), err.getvalue().strip()

    def add_rayban(self, *extra):
        code, out, _ = self.run_cli("add", "--name", "Ray-Ban Wayfarer RB2140", "--type", "model",
                                    "--query", "RB2140", "--exclude", "case,lens", *extra)
        self.assertEqual(code, 0)
        return json.loads(out)

    def commit(self, slug, offers=(), unavailable=(), *flags):
        path = self.home / "obs.json"
        path.write_text(json.dumps({"offers": list(offers), "unavailable": list(unavailable)}))
        return self.run_cli("commit", slug, "--offers", str(path), *flags)

    def snap(self, slug):
        return json.loads((self.home / "snapshots" / f"{slug}.json").read_text())

    # ------------------------------------------------------------- products

    def test_add_returns_schedule_and_prompt(self):
        out = self.add_rayban("--cadence", "fortnightly")
        self.assertEqual(out["slug"], "ray-ban-wayfarer-rb2140")
        minute, hour, dom, mon, dow = out["schedule"].split()
        self.assertEqual((hour, dom, mon, dow), ("8", "1,15", "*", "*"))
        self.assertNotIn(int(minute), (0, 30))
        self.assertIn('slug "ray-ban-wayfarer-rb2140"', out["prompt"])
        products = json.loads((self.home / "products.json").read_text())["products"]
        self.assertEqual(products[0]["exclude"], ["case", "lens"])

    def test_slugs_are_unique(self):
        self.add_rayban()
        self.assertEqual(self.add_rayban()["slug"], "ray-ban-wayfarer-rb2140-2")

    def test_barcode_checksum(self):
        self.assertTrue(pc.gtin_valid("9300601000007"[:-1] + str(self._check("930060100000"))))
        self.assertTrue(pc.gtin_valid("012345678905"))   # UPC-A
        self.assertTrue(pc.gtin_valid("96385074"))       # EAN-8
        self.assertFalse(pc.gtin_valid("012345678906"))
        self.assertFalse(pc.gtin_valid("12345"))
        code, _, err = self.run_cli("add", "--type", "barcode", "--query", "9300601234567")
        self.assertEqual(code, 2)
        self.assertIn("check digit", err)

    @staticmethod
    def _check(body):
        d = [int(c) for c in body]
        return (10 - sum(x * (3 if i % 2 == 0 else 1) for i, x in enumerate(reversed(d))) % 10) % 10

    def test_bad_cadence(self):
        code, _, err = self.run_cli("add", "--type", "model", "--query", "X1", "--cadence", "hourly")
        self.assertEqual(code, 2)

    def test_update_cadence_and_filters(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189)])
        code, out, _ = self.run_cli("update", slug, "--cadence", "daily")
        self.assertTrue(json.loads(out)["schedule"].endswith("8 * * *"))
        self.assertTrue((self.home / "snapshots" / f"{slug}.json").exists())
        code, out, _ = self.run_cli("update", slug, "--max", "300")
        self.assertTrue(json.loads(out)["reset_baseline"])
        self.assertFalse((self.home / "snapshots" / f"{slug}.json").exists())

    def test_pause_remove_find_list(self):
        slug = self.add_rayban()["slug"]
        self.run_cli("set-job", slug, "job123")
        _, out, _ = self.run_cli("pause", slug)
        self.assertEqual(json.loads(out)["cron_job_id"], "job123")
        _, out, _ = self.commit(slug, [offer(BAN, 189)])
        self.assertEqual(out, "[SILENT]")
        _, out, _ = self.run_cli("list")
        self.assertIn("paused", out)
        _, out, _ = self.run_cli("find", "rb 2140")
        self.assertEqual(json.loads(out)[0]["slug"], slug)
        _, out, _ = self.run_cli("remove", slug)
        self.assertEqual(json.loads(out)["cron_job_id"], "job123")
        self.assertEqual(self.run_cli("show", slug)[0], 3)

    # ------------------------------------------------------------- runs

    def test_baseline_then_silent(self):
        slug = self.add_rayban()["slug"]
        offers = [offer(BAN, 189), offer(DJ, 199, 9.95), offer(EBAY, 212.5, None, seller="optical_au"),
                  offer(ICONIC, 259)]
        code, out, _ = self.commit(slug, offers)
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("🆕 Now tracking: Ray-Ban Wayfarer RB2140"))
        self.assertIn("Best 3 of 4 AU retailers:", out)
        self.assertIn("2. David Jones — $208.95 (+ $9.95 del)", out)
        self.assertIn("3. eBay – optical_au — $212.50 (+ del?)", out)
        self.assertIn("Range: $189.00 – $259.00", out)
        code, out, _ = self.commit(slug, offers)
        self.assertEqual(out, "[SILENT]")
        snap = self.snap(slug)
        self.assertEqual(snap["top3"], ["sunglasshut.com", "davidjones.com", "ebay.com.au|optical_au"])
        self.assertEqual(snap["range"], {"low": 189.0, "high": 259.0, "retailers": 4})

    def test_price_drop_alert(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 205), offer(DJ, 199, 9.95), offer(ICONIC, 259)])
        _, out, _ = self.commit(slug, [offer(BAN, 189), offer(DJ, 199, 9.95), offer(ICONIC, 259)])
        self.assertTrue(out.startswith("📉 Ray-Ban Wayfarer RB2140 — best now $189.00 (was $205.00)"))
        self.assertIn("• Sunglass Hut: $205.00 → $189.00 (↓$16.00)", out)
        self.assertIn("1. Sunglass Hut — $189.00 (free del) ↓", out)
        self.assertIn("2. David Jones — $208.95 (+ $9.95 del) =", out)

    def test_rise_and_swap(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199), offer(ICONIC, 209), offer(MYER, 219)])
        _, out, _ = self.commit(slug, [offer(BAN, 229), offer(DJ, 199), offer(ICONIC, 209),
                                       offer(MYER, 219)])
        self.assertTrue(out.startswith("📈"))
        self.assertIn("• Myer entered the top 3 at $219.00", out)
        self.assertIn("• Sunglass Hut left the top 3 (now $229.00)", out)
        self.assertIn("• Range high: $219.00 → $229.00", out)

    def test_non_top3_move_is_silent_unless_high_changes(self):
        slug = self.add_rayban()["slug"]
        base = [offer(BAN, 189), offer(DJ, 199), offer(ICONIC, 209), offer(MYER, 260), offer(
            "https://www.bigw.com.au/rb2140", 240)]
        self.commit(slug, base)
        moved = base[:4] + [offer("https://www.bigw.com.au/rb2140", 235)]
        self.assertEqual(self.commit(slug, moved)[1], "[SILENT]")
        moved = base[:3] + [offer(MYER, 270), base[4]]
        self.assertIn("Range high: $260.00 → $270.00", self.commit(slug, moved)[1])

    def test_missing_retailer_is_carried_not_reported(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199), offer(ICONIC, 209)])
        for run in (1, 2):
            _, out, _ = self.commit(slug, [offer(DJ, 199), offer(ICONIC, 209)])
            self.assertEqual(out, "[SILENT]", f"run {run}")
            stale = [o for o in self.snap(slug)["offers"] if o["stale"]]
            self.assertEqual((stale[0]["retailer"], stale[0]["stale_runs"]), ("Sunglass Hut", run))
        _, out, _ = self.commit(slug, [offer(DJ, 199), offer(ICONIC, 209)])
        self.assertIn("Sunglass Hut left the top 3 (could not be checked for 3 runs)", out)
        _, out, _ = self.commit(slug, [offer(BAN, 189), offer(DJ, 199), offer(ICONIC, 209)])
        self.assertIn("Sunglass Hut entered the top 3 at $189.00", out)

    def test_stale_resets_when_page_loads(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199)])
        self.commit(slug, [offer(DJ, 199)])
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199)])
        self.assertTrue(all(o["stale_runs"] == 0 for o in self.snap(slug)["offers"]))

    def test_out_of_stock_leaves_top3(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199), offer(ICONIC, 209), offer(MYER, 219)])
        _, out, _ = self.commit(slug, [offer(BAN, 189, in_stock=False), offer(DJ, 199),
                                       offer(ICONIC, 209), offer(MYER, 219)])
        self.assertIn("• Sunglass Hut left the top 3 (out of stock)", out)
        self.assertTrue(out.startswith("📈"))
        snap = self.snap(slug)
        self.assertEqual(snap["unavailable"][0]["retailer"], "Sunglass Hut")
        _, out, _ = self.run_cli("plan", slug)
        urls = [r["url"] for r in json.loads(out)["recheck_first"]]
        self.assertIn(BAN, urls)

    def test_filters(self):
        slug = self.add_rayban("--max", "250")["slug"]
        offers = [
            offer(BAN, 189),
            offer(DJ, 150, title="Ray-Ban RB2140 Wayfarer - Refurbished"),
            offer(ICONIC, 99, title="Ray-Ban RB2140 replacement lens"),
            offer(MYER, 120, title="Ray-Ban Clubmaster RB3016"),
            offer("https://www.amazon.com/dp/x", 100),
            offer("https://www.staticice.com.au/x", 100),
            offer("https://www.bigw.com.au/x", 300),
            offer("https://www.kmart.com.au/x", 100, currency="USD"),
            offer(EBAY, 140),  # eBay without seller
        ]
        _, out, err = self.commit(slug, offers)
        self.assertIn("Only 1 AU retailer found:", out)
        log = (self.home / "logs" / f"{slug}.last.txt").read_text()
        for reason in ("not new", "excluded keyword 'lens'", "not confirmed on page", "overseas",
                       "comparison site", "above max_price", "AUD only", "seller name"):
            self.assertIn(reason, log)
        self.assertIn("notes: 8", err)

    def test_keyword_word_boundaries(self):
        self.assertFalse(pc.keyword_in("red", "Polarized Black"))
        self.assertTrue(pc.keyword_in("lens", "Replacement Lenses"))
        self.assertTrue(pc.keyword_in("2 pack", "Natural Bottle 260ml 2-Pack"))
        self.assertTrue(pc.keyword_in("260ml", "Natural Bottle 260 mL"))

    def test_one_per_retailer_keeps_cheapest(self):
        slug = self.add_rayban()["slug"]
        _, out, _ = self.commit(slug, [offer(BAN, 199), offer(BAN + "?v=2", 189),
                                       offer(EBAY, 150, seller="a"), offer(EBAY + "4", 160, seller="b")])
        self.assertIn("Best 3 of 3 AU retailers", out)
        self.assertIn("eBay – a — $150.00", out)
        self.assertIn("eBay – b — $160.00", out)
        self.assertIn("Sunglass Hut — $189.00", out)

    def test_barcode_needs_confirmation(self):
        code, out, _ = self.run_cli("add", "--name", "Bottle", "--type", "barcode",
                                    "--query", "0123-4567-8905")
        slug = json.loads(out)["slug"]
        bb = "https://www.babybunting.com.au/x"
        _, out, _ = self.commit(slug, [offer(bb, 30, title="Bottle"),
                                       offer(DJ, 31, title="Bottle", gtin="00012345678905"),
                                       offer(MYER, 32, title="Bottle", id_on_page=True),
                                       offer(ICONIC, 20, title="Bottle", gtin="012345678912",
                                             id_on_page=True)])
        self.assertIn("Best 2 of 2", out)
        self.assertNotIn("Baby Bunting", out)

    def test_no_results_keeps_previous(self):
        slug = self.add_rayban()["slug"]
        code, out, _ = self.commit(slug, [])
        self.assertEqual(code, 4)
        self.assertIn("nothing is saved yet", out)
        self.commit(slug, [offer(BAN, 189)])
        before = self.snap(slug)
        code, out, _ = self.commit(slug, [offer(BAN, 150, title="Ray-Ban RB2140 used")])
        self.assertEqual(code, 4)
        self.assertIn("Kept the previous result from Tue 13 Oct 8:17am", out)
        self.assertEqual(self.snap(slug), before)

    def test_always_message_and_show(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 189), offer(DJ, 199)])
        _, out, _ = self.commit(slug, [offer(BAN, 189), offer(DJ, 199)], (), "--always-message")
        self.assertTrue(out.startswith("No change since Tue 13 Oct 8:17am."))
        _, out, _ = self.run_cli("show", slug)
        self.assertIn("as of Tue 13 Oct 8:17am", out)
        self.assertIn("Range: $189.00 – $199.00 across 2 retailers", out)

    def test_dry_run_writes_nothing(self):
        slug = self.add_rayban()["slug"]
        _, out, _ = self.commit(slug, [offer(BAN, 189)], (), "--dry-run")
        self.assertIn("🆕", out)
        self.assertFalse((self.home / "snapshots" / f"{slug}.json").exists())

    def test_oneoff(self):
        path = self.home / "o.json"
        path.write_text(json.dumps([offer(BAN, 189)]))
        code, out, _ = self.run_cli("oneoff", "--name", "RB", "--type", "model", "--query", "RB2140",
                                    "--offers", str(path))
        self.assertEqual(code, 0)
        self.assertIn("one-off check (not tracked)", out)
        self.assertFalse((self.home / "products.json").exists())

    def test_legacy_snapshot_with_names_in_top3(self):
        slug = self.add_rayban()["slug"]
        legacy = {"version": 1, "slug": slug, "checked_at": "2026-10-12T08:00:00+11:00",
                  "offers": [{"retailer": "Sunglass Hut", "title": "t", "url": BAN, "price": 189.0,
                              "delivery": 0.0, "total": 189.0, "stale": False, "stale_runs": 0}],
                  "unavailable": [], "top3": ["Sunglass Hut"],
                  "range": {"low": 189.0, "high": 189.0, "retailers": 1}}
        (self.home / "snapshots").mkdir(exist_ok=True)
        (self.home / "snapshots" / f"{slug}.json").write_text(json.dumps(legacy))
        self.assertEqual(self.commit(slug, [offer(BAN, 189)])[1], "[SILENT]")

    def test_money_is_exact(self):
        slug = self.add_rayban()["slug"]
        self.commit(slug, [offer(BAN, 0.1, 0.2)])
        self.assertEqual(self.snap(slug)["offers"][0]["total"], 0.3)


if __name__ == "__main__":
    unittest.main()
