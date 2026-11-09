"""
wp_push.py — Pushes assembled pages into WordPress via REST API,
and resolves internal links from the keyword_map (anti-cannibalization).
"""
import json, requests, re
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
        ("mix",   "Mini Golden Retriever", "/"),
        ("core",  "Mini Golden Retriever", "/"),
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

    # 3. Evergreen links — homepage first (protects head term), then safe pillars.
    #    Deliberately EXCLUDES what_is and puppies pages: those compete with the
    #    homepage for the head term and for-sale intent.
    evergreen = [
        ("Mini Golden Retriever", "/"),
        ("Pricing Guide", owners.get("pricing")),
        ("Health Guarantee", owners.get("health")),
        ("Size & Growth", owners.get("size")),
        ("Temperament", owners.get("temperament")),
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
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Check if slug already exists on the live site (source of truth, not a local file)
    existing = requests.get(f"{config.WP_CPT_REST}?slug={slug}&status=any",
                            auth=auth, headers={"Accept": "application/json"}, timeout=30).json()
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
        r = requests.post(f"{config.WP_CPT_REST}/{pid}", json=payload, auth=auth, headers=headers, timeout=60)
    else:
        r = requests.post(config.WP_CPT_REST, json=payload, auth=auth, headers=headers, timeout=60)
    r.raise_for_status()
    result = r.json()
    _sync_rank_math(result.get("id"), content, slug, auth, headers)
    link = result.get("link", "")
    if not link:
        # Diagnostic: show what WordPress actually returned so we can see why
        print(f"    [debug] no link in response. status={r.status_code}, keys={list(result.keys())[:8]}, id={result.get('id')}", flush=True)
    return link

def _sync_rank_math(post_id, content, slug, auth, headers):
    """
    Mirror the page SEO into Rank Math's own fields (title, description, focus
    keyword) so the editor shows them filled. Values match what the plugin
    already outputs, so nothing changes for Google. Best-effort: never blocks a publish.
    """
    if not post_id:
        return
    try:
        base = config.WP_CPT_REST.split("/wp-json/")[0]
        kw = slug.replace("-", " ")
        meta = {
            "rank_math_title": f"{content['title']} — Mini Golden Retriever Pups",
            "rank_math_description": content.get("meta_description", ""),
            "rank_math_focus_keyword": kw,
        }
        requests.post(f"{base}/wp-json/rankmath/v1/updateMeta",
                      json={"objectID": post_id, "objectType": "post", "meta": meta},
                      auth=auth, headers=headers, timeout=30)
    except Exception as e:
        print(f"    (rank math sync warning: {e})", flush=True)

class SkipExisting(Exception):
    """Raised when a page already exists and must not be overwritten."""
    pass

def bulk_existing_slugs(slugs):
    """
    Fast check: which of these slugs already exist on the site?
    Queries WordPress in pages of 100 and returns a set of existing slugs.
    Far faster than checking one slug at a time.
    """
    auth = HTTPBasicAuth(config.WP_USER, config.WP_APP_PASS)
    headers = {"Accept": "application/json"}
    existing = set()
    # WP REST allows filtering by slug list; chunk to keep URLs sane
    CHUNK = 30
    for i in range(0, len(slugs), CHUNK):
        chunk = slugs[i:i+CHUNK]
        try:
            params = "&".join(f"slug[]={s}" for s in chunk) + "&per_page=100&status=any&_fields=slug"
            r = requests.get(f"{config.WP_CPT_REST}?{params}", auth=auth, headers=headers, timeout=30)
            if r.ok:
                for item in r.json():
                    if item.get("slug"):
                        existing.add(item["slug"])
        except Exception as e:
            print(f"  (bulk check warning: {e})", flush=True)
    return existing

def make_slug(page):
    intent = page["intent"]
    category, _, detail = intent.partition(":")
    detail = detail.strip() or category.strip()
    base = detail.lower().replace(" ", "-").replace("/", "-")
    base = "".join(c for c in base if c.isalnum() or c == "-")

    # If the detail is generic (e.g. "general"), prefix the category to stay unique.
    generic = {"general", "guide", "overview", "info"}
    if base in generic or detail.lower() in generic:
        cat = "".join(c for c in category.strip().lower().replace(" ", "-") if c.isalnum() or c == "-")
        base = f"{cat}-{base}"

    base = re.sub(r"-+", "-", base).strip("-")
    if page.get("location"):
        loc = page["location"].lower().replace(", ", "-").replace(" ", "-")
        loc = "".join(c for c in loc if c.isalnum() or c == "-")
        return f"mini-golden-retriever-{base}-{loc}"
    return f"mini-golden-retriever-{base}"
