"""
run.py — MGR Engine orchestrator.
Runs the full pipeline: load page map → for each page, resolve pricing,
generate content (Claude), assemble HTML, push to WordPress.
Phased in batches. Tracks state so reruns don't duplicate (anti-cannibalization).

USAGE:
    export ANTHROPIC_API_KEY=sk-ant-...
    export WP_USER=your_wp_user
    export WP_APP_PASS="xxxx xxxx xxxx xxxx"
    python run.py --batch quickwins        # generate the high-value quick-win pages first
    python run.py --batch all --live        # generate everything and push live
    python run.py --batch all               # dry run (writes HTML to output/ only)
"""
import json, os, time, argparse, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "engine"))

import config
import pricing as pricing_mod
import generator
import assembler
import wp_push

def load_json(p):
    with open(p) as f: return json.load(f)

def load_state():
    if os.path.exists(config.STATE_FILE):
        return load_json(config.STATE_FILE)
    return {"completed": [], "owned_keywords": {}}

def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=1)

def build_sibling_map(all_pages):
    """
    For each page, find related pages in the same silo (same US state)
    so each page can link to its neighbors — builds hierarchy/siloing.
    Returns {slug: [(url, anchor), ...]}.
    """
    # all states from the gazetteer (longest first so "West Virginia" wins over "Virginia")
    try:
        US_STATES = sorted(json.load(open(os.path.join(config.DATA_DIR, "gazetteer.json")))["states"], key=len, reverse=True)
    except Exception:
        US_STATES = ["Texas","California","Florida","New York","North Carolina","Georgia",
                     "South Carolina","Ohio","Pennsylvania","Virginia","Tennessee","Illinois",
                     "Michigan","Colorado","Arizona","Washington","Massachusetts","New Jersey"]
    # group pages by the state they belong to
    by_state = {}
    for p in all_pages:
        loc = p.get("location", "")
        state = next((s for s in US_STATES if s in loc), None)
        if state:
            by_state.setdefault(state, []).append(p)

    sibling_map = {}
    for p in all_pages:
        loc = p.get("location", "")
        state = next((s for s in US_STATES if s in loc), None)
        if not state:
            continue
        slug = wp_push.make_slug(p)
        sibs = []
        for other in by_state[state]:
            if other is p:
                continue
            o_slug = wp_push.make_slug(other)
            o_loc = other.get("location", "")
            anchor = f"mini golden retriever puppies in {o_loc}" if o_loc else "mini golden retriever puppies"
            sibs.append((f"/guide/{o_slug}/", anchor))
        if sibs:
            sibling_map[slug] = sibs[:4]  # cap at 4 siblings per page
    return sibling_map

def parse_pagemap():
    """Turn the flat pagemap list into structured page dicts."""
    pm = load_json(config.PAGEMAP)
    pages = []
    for entry in pm["pages"]:
        # entries look like "price: how much does it cost | Texas" or "... | (national)"
        intent, _, loc = entry.partition(" | ")
        loc = "" if "(national)" in loc else loc.strip()
        # gather keywords for this intent from pages.json
        pages.append({"intent": intent.strip(), "location": loc, "keywords": [intent.strip()]})
    return pages

def is_quickwin(page, pages_data):
    """Quick win = intent cluster already ranking pos 4-20 with decent volume."""
    sig = page["intent"]
    info = pages_data.get(sig)
    if not info: return False
    return 4 <= info.get("best_pos", 99) <= 20 and info.get("volume", 0) >= 300

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="quickwins", choices=["quickwins", "all"])
    ap.add_argument("--live", action="store_true", help="push to WP (overrides DRY_RUN)")
    ap.add_argument("--limit", type=int, default=config.BATCH_SIZE)
    args = ap.parse_args()

    if args.live:
        config.DRY_RUN = False
        # PUBLISH_STATUS comes from config.py — do not override here.

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    data       = load_json(config.DATA_LAYER)
    pages_data = load_json(os.path.join(config.DATA_DIR, "pages.json"))
    kw_map     = wp_push.load_keyword_map()
    state      = load_state()
    completed_set = set(state.get("completed", []))

    pages = parse_pagemap()
    sibling_map = build_sibling_map(pages)
    if args.batch == "quickwins":
        pages = [p for p in pages if is_quickwin(p, pages_data)]

    # enrich keywords from pages.json
    for p in pages:
        info = pages_data.get(p["intent"])
        if info: p["keywords"] = info["keywords"][:6]

    pricing = pricing_mod.get_live_pricing()
    print(f"[pricing] {pricing_mod.price_range_str(pricing)} (live={pricing['live']})", flush=True)
    print(f"[batch] {args.batch}: {len(pages)} candidate pages | DRY_RUN={config.DRY_RUN}", flush=True)

    blocked       = set(data.get("cannibalization_warning", {}).get("blocked_national_intents", []))
    blocked_cats  = set(data.get("cannibalization_warning", {}).get("blocked_categories", []))
    blocked_dupes = set(data.get("cannibalization_warning", {}).get("blocked_duplicate_intents", []))

    # ── Apply the blocklists once, up front, and compute each surviving
    # page's slug. This gives us the real candidate list before we touch
    # WordPress or the state file at all.
    candidates = []
    for page in pages:
        if page["intent"].strip() in blocked_dupes:
            print(f"  ⏭ skipped (duplicate of puppy price): {page['intent']}", flush=True)
            continue
        if page["intent"].split(":")[0].strip() in blocked_cats:
            print(f"  ⏭ skipped (protects homepage): {page['intent']}", flush=True)
            continue
        if not page.get("location") and page["intent"] in blocked:
            print(f"  ⏭ skipped (would cannibalize existing page): {page['intent']}", flush=True)
            continue
        candidates.append((page, wp_push.make_slug(page)))

    # ── Bulk existence check — replaces the old one-GET-per-page check.
    # Only asks WordPress about slugs we don't already know are done, and
    # asks about ALL of them in a handful of chunked requests (via
    # wp_push.bulk_existing_slugs), not one request per page.
    if not config.DRY_RUN:
        unknown_slugs = [slug for _, slug in candidates if slug not in completed_set]
        if unknown_slugs:
            print(f"[precheck] checking {len(unknown_slugs)} slugs against WordPress in bulk...", flush=True)
            existing_on_wp = wp_push.bulk_existing_slugs(unknown_slugs)
            if existing_on_wp:
                print(f"[precheck] {len(existing_on_wp)} already exist — marked done, no tokens used", flush=True)
                for slug in existing_on_wp:
                    if slug not in completed_set:
                        state["completed"].append(slug)
                        completed_set.add(slug)
                save_state(state)

    done = 0
    for page, slug in candidates:
        if slug in completed_set:
            continue
        if done >= args.limit:
            print(f"[batch] reached limit {args.limit}; rerun to continue")
            break
        try:
            print(f"  → generating: {slug}", flush=True)
            t0 = time.time()
            content = generator.generate_page_content(page, data, pricing, sibling_links=sibling_map.get(slug))
            links   = wp_push.resolve_internal_links(page, data, kw_map, state.get("owned_keywords", {}))
            body    = assembler.assemble_html(content, page, data, pricing, links)
            schema  = assembler.build_faq_schema(content, page, data, pricing, "/guide/" + slug + "/")

            # always write a local copy for review
            with open(os.path.join(config.OUTPUT_DIR, f"{slug}.html"), "w") as f:
                f.write(f"<!-- {content['title']} -->\n<!-- meta: {content.get('meta_description','')} -->\n{body}")

            if not config.DRY_RUN:
                try:
                    url = wp_push.push_page(content, body, schema, page, slug)
                    print(f"    pushed → {url}", flush=True)
                except wp_push.SkipExisting as se:
                    print(f"    ⏭ skipped (protected): {se}", flush=True)
                    state["completed"].append(slug)  # mark so we don't retry
                    completed_set.add(slug)
                    save_state(state)
                    continue

            state["completed"].append(slug)
            completed_set.add(slug)
            state["owned_keywords"][page["intent"]] = slug
            save_state(state)
            done += 1
            print(f"    ✓ done in {time.time()-t0:.0f}s ({done}/{args.limit})", flush=True)
            time.sleep(config.REQUEST_DELAY_SEC)
        except Exception as e:
            print(f"    ⚠ failed {slug}: {e}", flush=True)

    print(f"[done] generated {done} pages this run. Total completed: {len(state['completed'])}")

if __name__ == "__main__":
    main()
