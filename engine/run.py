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
import threading
from concurrent.futures import ThreadPoolExecutor
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
        # PUBLISH_STATUS comes from config.py ("publish") — do not override it here.

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    data       = load_json(config.DATA_LAYER)
    pages_data = load_json(os.path.join(config.DATA_DIR, "pages.json"))
    kw_map     = wp_push.load_keyword_map()
    state      = load_state()

    pages = parse_pagemap()
    if args.batch == "quickwins":
        pages = [p for p in pages if is_quickwin(p, pages_data)]

    # enrich keywords from pages.json
    for p in pages:
        info = pages_data.get(p["intent"])
        if info: p["keywords"] = info["keywords"][:6]

    pricing = pricing_mod.get_live_pricing()
    print(f"[pricing] {pricing_mod.price_range_str(pricing)} (live={pricing['live']})", flush=True)

    blocked = set(data.get("cannibalization_warning", {}).get("blocked_national_intents", []))

    # ── Build the work list: skip already-done (state) and cannibalizing pages up front ──
    completed_set = set(state.get("completed", []))
    todo = []
    for page in pages:
        slug = wp_push.make_slug(page)
        if slug in completed_set:
            continue
        if not page.get("location") and page["intent"] in blocked:
            continue
        page["_slug"] = slug
        todo.append(page)

    # One fast batch check against WordPress for which slugs already exist (protect them)
    print(f"[batch] {args.batch}: {len(todo)} candidate pages not in local state | DRY_RUN={config.DRY_RUN}", flush=True)
    if not config.DRY_RUN and todo:
        existing_slugs = wp_push.bulk_existing_slugs([p["_slug"] for p in todo])
        before = len(todo)
        kept = []
        for p in todo:
            if p["_slug"] in existing_slugs:
                state["completed"].append(p["_slug"])  # remember so we never re-check
            else:
                kept.append(p)
        todo = kept
        save_state(state)
        print(f"[batch] {before - len(todo)} already exist on site (protected & cached); {len(todo)} new to build", flush=True)

    # Respect the limit
    todo = todo[:args.limit]
    print(f"[batch] building {len(todo)} pages, up to {config.MAX_WORKERS} at a time", flush=True)

    done = 0
    published_urls = []
    lock = threading.Lock()

    def build_one(page):
        nonlocal done
        slug = page["_slug"]
        try:
            t0 = time.time()
            content = generator.generate_page_content(page, data, pricing)
            links   = wp_push.resolve_internal_links(page, data, kw_map, state.get("owned_keywords", {}))
            body    = assembler.assemble_html(content, page, data, pricing, links)
            schema  = assembler.build_faq_schema(content, page, data, pricing, "/guide/" + slug + "/")

            with open(os.path.join(config.OUTPUT_DIR, f"{slug}.html"), "w") as f:
                f.write(f"<!-- {content['title']} -->\n<!-- meta: {content.get('meta_description','')} -->\n{body}")

            url = ""
            if not config.DRY_RUN:
                try:
                    url = wp_push.push_page(content, body, schema, page, slug)
                except wp_push.SkipExisting:
                    with lock:
                        state["completed"].append(slug)
                    return
            with lock:
                state["completed"].append(slug)
                state["owned_keywords"][page["intent"]] = slug
                done += 1
                if url:
                    published_urls.append((content["title"], url))
                    print(f"  ✓ {slug} → {url}  ({time.time()-t0:.0f}s) [{done}/{len(todo)}]", flush=True)
                else:
                    print(f"  ✓ {slug} (local) ({time.time()-t0:.0f}s) [{done}/{len(todo)}]", flush=True)
        except Exception as e:
            print(f"  ⚠ failed {slug}: {e}", flush=True)

    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as ex:
        list(ex.map(build_one, todo))

    save_state(state)
    print(f"[done] generated {done} pages this run. Total completed: {len(state['completed'])}")

    # Clean clickable summary of everything published this run (for quick mobile review)
    if published_urls:
        print("")
        print("=" * 60)
        print(f"✅ PUBLISHED THIS RUN ({len(published_urls)} pages) — tap to review:")
        print("=" * 60)
        for title, url in published_urls:
            print(f"• {title}")
            print(f"  {url}")
        print("=" * 60)

if __name__ == "__main__":
    main()
