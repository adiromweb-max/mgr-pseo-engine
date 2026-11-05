"""
Weekly indexing monitor for MiniGoldenRetrievers /guide/ pages.

What it does (all via official Google Search Console API):
  1. Lists every PUBLISHED mgr_page from WordPress.
  2. Inspects each URL (URL Inspection API) -> indexed / not indexed + reason.
  3. Resubmits the sitemap (safe, official way to nudge Google).
  4. Writes data/index_report.json and prints a readable summary.

NOTE: Google offers no official 'request indexing' API for normal pages
(the Indexing API is for job/livestream pages only), so we use sitemap
submission + monitoring, and flag pages stuck 'Discovered/Crawled - not indexed'.

Env: GSC_SERVICE_ACCOUNT_JSON (full JSON), GSC_SITE_URL (e.g. https://www.minigoldenretrievers.com/)
     WP_USER / WP_APP_PASS (read published list)
"""
import json, os, sys, datetime, requests
import config

SITEMAP_URL = "https://www.minigoldenretrievers.com/sitemap_index.xml"


def published_urls():
    urls, page = [], 1
    while True:
        r = requests.get(
            f"{config.WP_BASE_URL}/wp-json/wp/v2/{config.WP_CPT_SLUG}",
            params={"status": "publish", "per_page": 100, "page": page, "_fields": "link"},
            auth=(os.environ["WP_USER"], os.environ["WP_APP_PASS"]),
            timeout=30)
        if r.status_code == 400:  # past last page
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        urls += [x["link"] for x in batch]
        page += 1
    return urls


def main():
    raw = os.environ.get("GSC_SERVICE_ACCOUNT_JSON", "").strip()
    site = os.environ.get("GSC_SITE_URL", "").strip()
    if not raw or not site:
        print("GSC_SERVICE_ACCOUNT_JSON / GSC_SITE_URL not set - skipping index check.")
        return 0

    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/webmasters"])
    s = AuthorizedSession(creds)

    # 1) resubmit sitemap
    from urllib.parse import quote
    sm = s.put(f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}"
               f"/sitemaps/{quote(SITEMAP_URL, safe='')}")
    print(f"[sitemap] resubmit -> HTTP {sm.status_code}" + ("" if sm.ok else f" {sm.text[:400]}"))

    # 2) inspect each published URL
    urls = published_urls()
    print(f"[inspect] {len(urls)} published pages")
    report, indexed = [], 0
    for u in urls:
        r = s.post("https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                   json={"inspectionUrl": u, "siteUrl": site, "languageCode": "en-US"})
        if r.status_code != 200:
            report.append({"url": u, "error": f"HTTP {r.status_code}: {r.text[:200]}"})
            print(f"  ! {u} -> HTTP {r.status_code}")
            continue
        ix = r.json().get("inspectionResult", {}).get("indexStatusResult", {})
        verdict, state = ix.get("verdict"), ix.get("coverageState")
        ok = verdict == "PASS"
        indexed += ok
        report.append({"url": u, "verdict": verdict, "state": state,
                       "lastCrawl": ix.get("lastCrawlTime"),
                       "canonical": ix.get("googleCanonical")})
        print(f"  {'✓' if ok else '·'} {u} -> {state}")

    out = {"checked": datetime.datetime.utcnow().isoformat() + "Z",
           "published": len(urls), "indexed": indexed, "pages": report}
    os.makedirs("data", exist_ok=True)
    json.dump(out, open("data/index_report.json", "w"), indent=2)
    print(f"[summary] indexed {indexed}/{len(urls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
