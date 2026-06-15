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

def resolve_internal_links(page, data, kw_map, max_links=6):
    """
    Build internal links for a page. Rules:
    - Always link UP to the relevant existing owner/pillar page.
    - Link to adjacent clusters, never to a page that doesn't exist yet.
    - Never create a link whose anchor competes with this page's own keyword.
    """
    links = []
    owners = data["existing_owner_pages"]
    intent = page["intent"]

    # 1. Link up to the most relevant existing pillar
    pillar_map = {
        "price": ("Full Pricing Guide", owners.get("pricing")),
        "cost":  ("Full Pricing Guide", owners.get("pricing")),
        "sale":  ("Available Puppies",  owners.get("puppies for sale")),
        "size":  ("Lifespan & Size",    owners.get("lifespan")),
        "temperament": ("Temperament Guide", owners.get("temperament")),
        "mix":   ("What Is a Mini Golden?", owners.get("what is a mini golden retriever")),
        "core":  ("What Is a Mini Golden?", owners.get("what is a mini golden retriever")),
    }
    for key, (label, url) in pillar_map.items():
        if key in intent and url:
            links.append((label, url))
            break

    # 2. A couple of evergreen pillars every page can link to
    evergreen = [
        ("What Is a Mini Golden?", owners.get("what is a mini golden retriever")),
        ("Breeder Info", owners.get("breeder")),
        ("Available Puppies", owners.get("puppies for sale")),
    ]
    for label, url in evergreen:
        if url and (label, url) not in links:
            links.append((label, url))
        if len(links) >= max_links:
            break

    return links[:max_links]

# ── WordPress REST push ─────────────────────────────────────────────
def push_page(content, html_body, schema, page, slug):
    """Create or update an mgr_page post via REST. Returns the post URL."""
    auth = HTTPBasicAuth(config.WP_USER, config.WP_APP_PASS)
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
    # check if slug exists → update instead of duplicate
    existing = requests.get(f"{config.WP_CPT_REST}?slug={slug}", auth=auth, timeout=30).json()
    if existing:
        pid = existing[0]["id"]
        r = requests.post(f"{config.WP_CPT_REST}/{pid}", json=payload, auth=auth, timeout=60)
    else:
        r = requests.post(config.WP_CPT_REST, json=payload, auth=auth, timeout=60)
    r.raise_for_status()
    return r.json().get("link", "")

def make_slug(page):
    base = page["intent"].split(":")[-1].strip().lower().replace(" ", "-").replace("/", "-")
    base = "".join(c for c in base if c.isalnum() or c == "-")
    if page.get("location"):
        loc = page["location"].lower().replace(", ", "-").replace(" ", "-")
        return f"mini-golden-retriever-{base}-{loc}"
    return f"mini-golden-retriever-{base}"
