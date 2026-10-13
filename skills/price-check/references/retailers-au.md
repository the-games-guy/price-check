# Australian retailers — hints

This is a starting list, not a limit: include any AU retailer that meets the hard rules. Use it to decide where to look.

## How retailers are identified
- The helper identifies a retailer by the **domain of the URL**, so you never need to normalise names yourself. The domains below get the canonical name shown. For any other domain, put a sensible name in `retailer`.
- The canonical names live in `RETAILERS` in `scripts/price_check.py`. If you add a row here, add it there too.
- **Marketplaces:** each seller counts as its own retailer — `eBay – <seller>`, `Amazon AU – <seller>`, `Catch – <seller>`, `Kogan Marketplace – <seller>`. Put the seller in `seller`. If the platform sells it itself, the name is `Amazon AU`, `Catch` or `Kogan`.
- These are rejected automatically: comparison sites (below), and overseas stores such as amazon.com, ebay.com and aliexpress.com.
- **Egress:** if Amy's browsing runs inside the sandbox, every domain here must be on the global `proxy.extra_allowed_hosts` list (see install.md, step 4).

## By category

| Category | Name | Domain |
|---|---|---|
| General / department | Amazon AU | amazon.com.au |
| | Big W | bigw.com.au |
| | Kmart | kmart.com.au |
| | Target | target.com.au |
| | Myer | myer.com.au |
| | David Jones | davidjones.com |
| | Catch | catch.com.au |
| | Kogan | kogan.com |
| | eBay | ebay.com.au |
| Electronics | JB Hi-Fi | jbhifi.com.au |
| | Harvey Norman | harveynorman.com.au |
| | The Good Guys | thegoodguys.com.au |
| | Officeworks | officeworks.com.au |
| | Bing Lee | binglee.com.au |
| | Apple Store AU | apple.com/au |
| | Mwave | mwave.com.au |
| | Scorptec | scorptec.com.au |
| | Umart | umart.com.au |
| | PLE Computers | ple.com.au |
| Baby | Baby Bunting | babybunting.com.au |
| | Baby Kingdom | babykingdom.com.au |
| | Chemist Warehouse | chemistwarehouse.com.au |
| | Priceline Pharmacy | priceline.com.au |
| | Toys"R"Us AU | toysrus.com.au |
| Sunglasses / fashion | Sunglass Hut | sunglasshut.com/au |
| | OPSM | opsm.com.au |
| | Specsavers | specsavers.com.au |
| | The Iconic | theiconic.com.au |
| | Glue Store | gluestore.com.au |
| | Surf Stitch | surfstitch.com |
| | General Pants Co. | generalpants.com.au |
| Sport / outdoors | Rebel | rebelsport.com.au |
| | BCF | bcf.com.au |
| | Anaconda | anacondastores.com |
| | Kathmandu | kathmandu.com.au |
| Home / hardware | Bunnings | bunnings.com.au |
| | Temple & Webster | templeandwebster.com.au |
| | Adairs | adairs.com.au |

## Price comparison sites (for discovery only)
Use these to find retailers, then open the retailer's own page to confirm. Never record a comparison site as the retailer.
- Google Shopping (`shopping.google.com` / search "Shopping" tab, AU region)
- StaticICE (`staticice.com.au`) — computers and electronics
- PriceHipster (`pricehipster.com`)
- Getprice (`getprice.com.au`)
- Shopbot (`shopbot.com.au`)
- PriceSpy (`pricespy.com.au`)
