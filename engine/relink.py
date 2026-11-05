"""
relink.py — keeps the internal-link silo fresh WITHOUT regenerating pages (zero AI tokens).

Every page that is PUBLISHED gets a "More Mini Golden Retriever guides in <State>" block linking to the
other PUBLISHED pages of the same state (state hub first). When a new page goes live, all its
siblings pick up a link to it on the next run. Drafts are never linked (they'd 404 for visitors).

Idempotent: the block carries data-mgr-auto="silo" and is replaced in place. Only the page
content is updated; status/slug/meta are untouched.

Usage: python -m engine.relink [--apply]   (default = dry run: prints what would change)
"""
import json, os, re, sys, hashlib
import requests
from requests.auth import HTTPBasicAuth
import config
from engine import wp_push

MAX_LINKS = 12
BLOCK_RE = re.compile(r'<div class="mgr-related mgr-silo" data-mgr-auto="silo">.*?</div>', re.S)
VARIANTS = ["Mini Golden Retriever puppy price in {l}", "Mini Golden Retriever puppies in {l}", "{l} Mini Golden Retriever puppy prices"]


def parse(entry):
    intent, _, loc = entry.partition(" | ")
    return {"intent": intent.strip(), "location": "" if "(national)" in loc else loc.strip()}


def state_of(loc, states):
    if loc in states:
        return loc
    tail = loc.split(", ")[-1] if ", " in loc else ""
    return tail if tail in states else None


def anchor(loc, target_slug):
    i = int(hashlib.md5(target_slug.encode()).hexdigest(), 16) % len(VARIANTS)
    return VARIANTS[i].format(l=loc)


def build_block(me, members, states):
    st = state_of(me["location"], states)
    sibs = [m for m in members if m["slug"] != me["slug"] and state_of(m["location"], states) == st]
    sibs.sort(key=lambda m: (m["location"] != st, m["location"]))   # hub first, then A-Z
    sibs = sibs[:MAX_LINKS]
    if not sibs:
        return ""
    lis = "".join(f'<li><a href="/guide/{m["slug"]}/">{anchor(m["location"], m["slug"])} →</a></li>' for m in sibs)
    return (f'<div class="mgr-related mgr-silo" data-mgr-auto="silo"><h3>More Mini Golden Retriever Guides in {st}</h3>'
            f'<ul>{lis}</ul></div>')


def apply_block(html, block):
    if BLOCK_RE.search(html):
        return BLOCK_RE.sub(block, html) if block else BLOCK_RE.sub("", html)
    if not block:
        return html
    if '<div class="mgr-cta">' in html:
        return html.replace('<div class="mgr-cta">', block + '\n<div class="mgr-cta">', 1)
    return html + block


def main():
    apply = "--apply" in sys.argv
    gaz = json.load(open(os.path.join(config.DATA_DIR, "gazetteer.json")))
    states = set(gaz["states"])
    pm = json.load(open(config.PAGEMAP))
    slug_loc = {}
    for e in pm["pages"]:
        p = parse(e)
        slug_loc[wp_push.make_slug(p)] = p["location"]

    auth = HTTPBasicAuth(config.WP_USER, config.WP_APP_PASS)
    pages, n = [], 1
    while True:
        r = requests.get(config.WP_CPT_REST, auth=auth, timeout=40,
                         params={"status": "publish", "per_page": 100, "page": n,
                                 "context": "edit", "_fields": "id,slug,content"})
        if r.status_code == 400:
            break
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        pages += b
        n += 1
    members = []
    for p in pages:
        if p["slug"] in slug_loc and slug_loc[p["slug"]]:
            members.append({"id": p["id"], "slug": p["slug"], "location": slug_loc[p["slug"]],
                            "raw": p["content"]["raw"]})
    print(f"[relink] {len(members)} published engine pages | {'APPLY' if apply else 'DRY RUN'}")
    changed = 0
    for m in members:
        new = apply_block(m["raw"], build_block(m, members, states))
        if new == m["raw"]:
            continue
        changed += 1
        links = len(re.findall(r'<li>', BLOCK_RE.search(new).group(0))) if BLOCK_RE.search(new) else 0
        print(f"  ~ {m['slug']}: silo block -> {links} links")
        if apply:
            u = requests.post(f"{config.WP_CPT_REST}/{m['id']}", json={"content": new}, auth=auth, timeout=60)
            u.raise_for_status()
    print(f"[relink] {changed} page(s) {'updated' if apply else 'would change'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
