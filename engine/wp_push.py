"""
wp_push.py — Pushes assembled pages into WordPress via REST API,
and resolves internal links from the keyword_map (anti-cannibalization).
"""
import json, requests
from requests.auth import HTTPBasicAuth
import config

# ── Internal link resolution (silo + anti-cannibalization) ──────────
def load_keyword_map():
    with open(config.KEYWORD_MAP) as f:
        return json.load(f)

def resolve_internal_links(page, data, kw_map, completed_pages=None, max_links=8):
    """
    True hierarchical silo:
    - Link UP to the most relevant pillar (verified real URL).
    - Link to SIBLING pages the engine already created in the same cluster.
    - Link to a few evergreen pillars.
    All URLs verified real or engine-created; never broken.
    """
    owners = data["existing_owner_pages"]
    intent = page["intent"]
    links = []

    # 1. Up to the most relevant pillar
    pillar_map = [
        ("price", "Pricing Guide", owners.get("pricing")),
        ("cost",  "Pricing Guide", owners.get("pricing")),
        ("size",  "Size & Growth Chart", owners.get("size")),
        ("grown", "Size & Growth Chart", owners.get("size")),
        ("weight","Size & Growth Chart", owners.get("size")),
        ("temperament", "Temperament Guide", owners.get("temperament")),
        ("lifespan", "Lifespan Guide", owners.get("lifespan")),
        ("mix",   "What Is a Mini Golden?", owners.get("what_is")),
        ("core",  "What Is a Mini Golden?", owners.get("what_is")),
        ("variation", "Size & Growth Chart", owners.get("size")),
    ]
    cluster_key = None
    for key, label, url in pillar_map:
        if key in intent and url and (label, url) not in links:
            links.append((label, url))
            cluster_key = key
            break

    # 2. SIBLING links — other engine-created pages in the same cluster (the silo)
    if completed_pages and cluster_key:
        siblings = []
        for sib_intent, sib_slug in completed_pages.items():
            if sib_intent == intent:
                continue
            if cluster_key in sib_intent:  # same cluster
                # human label from the sibling intent
                label = sib_intent.split(":")[-1].strip().title()
                siblings.append((label, "/guide/" + sib_slug + "/"))
        # add up to 3 siblings
        for s in siblings[:3]:
            if s not in links:
                links.append(s)

    # 3. Evergreen pillars (verified real URLs)
    evergreen = [
        ("What Is a Mini Golden?", owners.get("what_is")),
        ("Pricing Guide", owners.get("pricing")),
        ("Available Puppies", owners.get("puppies")),
        ("Health Guarantee", owners.get("health")),
        ("Size & Growth", owners.get("size")),
    ]
    for label, url in evergreen:
        if url and (label, url) not in links:
            links.append((label, url))
        if len(links) >= max_links:
            break

    return links[:max_links]

# ── WordPress REST push ─────────────────────────────────────────────
def push_page(content, html_body, schema, page, slug, allow_update=False):
    """
    Create an mgr_page post via REST. Returns the post URL.
    SAFETY: by default, if a page with this slug already exists, we SKIP it
    (never overwrite an indexed/ranking page). Only updates if allow_update=True
    (used for an explicit, intentional refresh — not the default run).
    """
    auth = HTTPBasicAuth(config.WP_USER, config.WP_APP_PASS)

    # Check if slug already exists on the live site (source of truth, not a local file)
    existing = requests.get(f"{config.WP_CPT_REST}?slug={slug}&status=any", auth=auth, timeout=30).json()
    if existing:
        if not allow_update:
            # Protect the existing page — do not touch it.
            raise SkipExisting(f"page already exists (id {existing[0]['id']}), skipping to protect it")
        pid = existing[0]["id"]

    payload = {
        "title":   content["title"],
        "slug":    slug,
        "content": html_body,
        "status":  config.PUBLISH_STATUS,
        "excerpt": content.get("meta_description", ""),
        "meta": {
            "mgr_seo_title": content["title"],
            "mgr_meta_desc": content.get("meta_description", ""),
            "mgr_schema":    schema,
            "mgr_intent":    page["intent"],
            "mgr_location":  page.get("location", ""),
        },
    }

    if existing and allow_update:
        r = requests.post(f"{config.WP_CPT_REST}/{pid}", json=payload, auth=auth, timeout=60)
    else:
        r = requests.post(config.WP_CPT_REST, json=payload, auth=auth, timeout=60)
    r.raise_for_status()
    return r.json().get("link", "")

class SkipExisting(Exception):
    """Raised when a page already exists and must not be overwritten."""
    pass

def make_slug(page):
    base = page["intent"].split(":")[-1].strip().lower().replace(" ", "-").replace("/", "-")
    base = "".join(c for c in base if c.isalnum() or c == "-")
    if page.get("location"):
        loc = page["location"].lower().replace(", ", "-").replace(" ", "-")
        return f"mini-golden-retriever-{base}-{loc}"
    return f"mini-golden-retriever-{base}"
