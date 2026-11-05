"""
gsc_loop.py — the long-term feedback loop for the MGR (Mini Golden Retrievers) engine.

Every week it:
  1. Pulls Search Console data for all /guide/ pages (last 28 days + the 28 before, for trends).
  2. Saves a dated snapshot (data/gsc/snapshot-YYYY-MM-DD.json) -> feeds the monthly report.
  3. Analyses it -> data/gsc_insights.json:
       - strengthen:     queries a page already shows for (pos 6-30) -> what to reinforce
       - low_ctr:        pages with many impressions but weak CTR (title/meta candidates)
       - cannibalization queries where 2+ /guide/ pages split the impressions
       - geo_demand:     locations people actually search for ("mini golden retriever puppies <city>")
  4. AUTO-EXPANDS data/final_pagemap.json so the engine never runs dry:
       demand-driven locations first, then cities in states that already perform,
       then population order. State hub is always added before its cities.
       Hard cap: MGR_MAX_PAGES (default 280).

Env: GSC_SERVICE_ACCOUNT_JSON, GSC_SITE_URL  (missing -> skips cleanly)
     MGR_AUTO_EXPAND=false  to disable step 4
"""
import json, os, re, sys, glob, datetime
from urllib.parse import quote
import config

GUIDE = "/guide/"
MIN_IMPR_QUERY = 10
MAX_ADD_PER_RUN = 10
PENDING_LOW = 16          # top up the queue when fewer than this many pages remain
DATA = config.DATA_DIR
SNAP_DIR = os.path.join(DATA, "gsc")


# ───────────────────────── Search Console fetch ─────────────────────────
def _session():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GSC_SERVICE_ACCOUNT_JSON"]),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return AuthorizedSession(creds)


def fetch(s, site, start, end, dims):
    url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(site, safe='')}/searchAnalytics/query"
    rows, start_row = [], 0
    while True:
        body = {"startDate": start, "endDate": end, "dimensions": dims, "rowLimit": 25000,
                "startRow": start_row,
                "dimensionFilterGroups": [{"filters": [
                    {"dimension": "page", "operator": "contains", "expression": GUIDE}]}]}
        r = s.post(url, json=body)
        if not r.ok:
            print(f"[gsc] HTTP {r.status_code} from Search Console: {r.text[:600]}", flush=True)
            print("[gsc] Check: (1) Search Console API enabled in the Google Cloud project, "
                  "(2) the service account email is added as a user on THIS exact property, "
                  "(3) GSC_SITE_URL matches the property exactly.", flush=True)
        r.raise_for_status()
        batch = r.json().get("rows", [])
        rows += batch
        if len(batch) < 25000:
            return rows
        start_row += 25000


def summarize(rows_pages, rows_pq):
    pages = {}
    for r in rows_pages:
        u = r["keys"][0]
        pages[u] = {"clicks": r["clicks"], "impressions": r["impressions"],
                    "ctr": r["ctr"], "position": round(r["position"], 1), "queries": []}
    for r in rows_pq:
        u, q = r["keys"]
        pages.setdefault(u, {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0, "queries": []})
        pages[u]["queries"].append({"q": q, "clicks": r["clicks"], "impr": r["impressions"],
                                    "pos": round(r["position"], 1)})
    for p in pages.values():
        p["queries"].sort(key=lambda x: -x["impr"])
        p["queries"] = p["queries"][:40]
    return pages


def totals(pages):
    c = sum(p["clicks"] for p in pages.values())
    i = sum(p["impressions"] for p in pages.values())
    pos = (sum(p["position"] * p["impressions"] for p in pages.values()) / i) if i else 0
    return {"clicks": c, "impressions": i, "avg_position": round(pos, 1),
            "pages_with_impressions": sum(1 for p in pages.values() if p["impressions"] > 0)}


# ───────────────────────────── analysis ─────────────────────────────
def analyse(cur_pages, gaz, known_locs):
    strengthen, low_ctr, qpages = [], [], {}
    for u, p in cur_pages.items():
        cands = [q for q in p["queries"] if q["impr"] >= MIN_IMPR_QUERY and 6 <= q["pos"] <= 30]
        if cands:
            strengthen.append({"page": u, "queries": cands[:5]})
        if p["impressions"] >= 100 and p["ctr"] < 0.01 and p["position"] <= 10:
            low_ctr.append({"page": u, "impressions": p["impressions"], "ctr": round(p["ctr"], 4),
                            "position": p["position"]})
        for q in p["queries"]:
            qpages.setdefault(q["q"], []).append((u, q["impr"]))
    cannibal = []
    for q, lst in qpages.items():
        tot = sum(i for _, i in lst)
        if len(lst) >= 2 and tot >= MIN_IMPR_QUERY:
            big = [(u, i) for u, i in lst if i / tot >= 0.25]
            if len(big) >= 2:
                cannibal.append({"query": q, "impressions": tot,
                                 "pages": [{"page": u, "impr": i} for u, i in sorted(big, key=lambda x: -x[1])]})
    cannibal.sort(key=lambda x: -x["impressions"])

    demand = geo_demand(cur_pages, gaz, known_locs)
    return {"generated": datetime.date.today().isoformat(),
            "strengthen": sorted(strengthen, key=lambda x: -x["queries"][0]["impr"])[:25],
            "low_ctr": low_ctr, "cannibalization": cannibal[:25], "geo_demand": demand}


def _find_locations(query, gaz):
    """Return 'City, State' / 'State' labels mentioned in a query. Ambiguous city names
    (same name in several states) are only accepted when the state is in the query too."""
    q = " " + re.sub(r"[^a-z0-9' ]", " ", query.lower()) + " "
    states = [s for s in gaz["states"] if f" {s.lower()} " in q]
    by_name = {}
    for name, st in gaz["cities"]:
        by_name.setdefault(name, []).append(st)
    out = []
    for name, sts in by_name.items():
        if f" {name.lower()} " in q:
            if len(sts) == 1 and name not in AMBIGUOUS:
                out.append(f"{name}, {sts[0]}")
            else:
                for st in sts:
                    if st in states:
                        out.append(f"{name}, {st}")
    if not out:
        out = list(states)
    return out


AMBIGUOUS = {"Columbia", "Springfield", "Portland", "Arlington", "Fayetteville", "Charleston",
             "Wilmington", "Rochester", "Jackson", "Lancaster", "Franklin", "Aurora", "Salem",
             "Vancouver", "Lincoln", "Manchester", "Albany", "Augusta", "Kansas City"}


def geo_demand(cur_pages, gaz, known_locs):
    demand = {}
    for p in cur_pages.values():
        for q in p["queries"]:
            if "golden" not in q["q"].lower():
                continue
            for loc in _find_locations(q["q"], gaz):
                demand[loc] = demand.get(loc, 0) + q["impr"]
    return dict(sorted(demand.items(), key=lambda x: -x[1]))


# ───────────────────────── auto-expansion ─────────────────────────
def _parse(entry):
    intent, _, loc = entry.partition(" | ")
    return {"intent": intent.strip(), "location": "" if "(national)" in loc else loc.strip()}


def pending_count(pm, state):
    from engine import wp_push
    done = set(state.get("completed", []))
    return sum(1 for e in pm["pages"] if wp_push.make_slug(_parse(e)) not in done)


def expand_pagemap(pm, gaz, demand, state_perf, pending, max_total):
    """Return list of new location labels added to pm (mutates pm)."""
    existing = {_parse(e)["location"] for e in pm["pages"]}
    if len(pm["pages"]) >= max_total:
        return []
    room = min(MAX_ADD_PER_RUN, max_total - len(pm["pages"]))
    state_names = set(gaz["states"])
    city_state = {f"{n}, {s}": s for n, s in gaz["cities"]}
    # existing cities not in the gazetteer still tell us which states are in the map
    in_map_states = {l for l in existing if l in state_names} | \
                    {l.split(", ")[-1] for l in existing if ", " in l}

    ranked = []   # (score, location)
    for loc, impr in demand.items():
        if loc not in existing and (loc in state_names or loc in city_state):
            ranked.append((1_000_000 + impr, loc))
    # fill only when the queue is running low
    if pending < PENDING_LOW:
        for rank, (n, s) in enumerate(gaz["cities"]):
            loc = f"{n}, {s}"
            if loc in existing:
                continue
            score = 1000 - rank + (500 + 10 * state_perf.get(s, 0) if s in in_map_states else 0)
            ranked.append((score, loc))
        for s in gaz["states"]:
            if s not in existing and s not in in_map_states:
                ranked.append((100, s))
    ranked.sort(key=lambda x: -x[0])

    added = []
    def add(label):
        pm["pages"].append(f"price: puppy price | {label}")
        existing.add(label); added.append(label)

    for _, loc in ranked:
        if len(added) >= room:
            break
        if loc in existing:
            continue
        if loc in state_names:
            add(loc)
        else:
            st = city_state.get(loc) or loc.split(", ")[-1]
            if st not in existing:           # hub first
                if len(added) + 2 > room:
                    continue
                add(st)
            add(loc)
    if added:
        pm["total"] = len(pm["pages"])
        pm["new_to_generate"] = len(pm["pages"]) - pm.get("existing_already_built", 0)
    return added


def state_performance(cur_pages, gaz):
    perf = {}
    for u, p in cur_pages.items():
        for s in gaz["states"]:
            if s.lower().replace(" ", "-") in u:
                perf[s] = perf.get(s, 0) + p["impressions"]
                break
    return perf


# ───────────────────────────── main ─────────────────────────────
def main():
    site = os.environ.get("GSC_SITE_URL", "").strip()
    try:
        s = _session()
    except Exception as e:
        print(f"[gsc] no Search Console session ({e})", flush=True)
        s = None
    end = datetime.date.today() - datetime.timedelta(days=3)         # GSC data lags ~2-3 days
    cs, ce = end - datetime.timedelta(days=27), end
    ps, pe = cs - datetime.timedelta(days=28), cs - datetime.timedelta(days=1)

    try:
        if s is None:
            raise RuntimeError("GSC credentials missing")
        cur_pages = summarize(fetch(s, site, str(cs), str(ce), ["page"]),
                              fetch(s, site, str(cs), str(ce), ["page", "query"]))
        prev_pages = summarize(fetch(s, site, str(ps), str(pe), ["page"]), [])
    except Exception as e:
        print(f"[gsc] Search Console unavailable ({e}); continuing without GSC data", flush=True)
        cur_pages, prev_pages = {}, {}
    snap = {"date": datetime.date.today().isoformat(),
            "window": {"current": [str(cs), str(ce)], "previous": [str(ps), str(pe)]},
            "totals": totals(cur_pages), "prev_totals": totals(prev_pages),
            "pages": cur_pages,
            "prev_pages": {u: {k: v for k, v in p.items() if k != "queries"} for u, p in prev_pages.items()}}
    os.makedirs(SNAP_DIR, exist_ok=True)
    json.dump(snap, open(os.path.join(SNAP_DIR, f"snapshot-{snap['date']}.json"), "w"), indent=1)
    for old in sorted(glob.glob(os.path.join(SNAP_DIR, "snapshot-*.json")))[:-24]:
        os.remove(old)
    print(f"[gsc] {len(cur_pages)} pages with data | impressions {snap['totals']['impressions']} "
          f"(prev {snap['prev_totals']['impressions']}) clicks {snap['totals']['clicks']}")

    gaz = json.load(open(os.path.join(DATA, "gazetteer.json")))
    pm = json.load(open(config.PAGEMAP))
    known = {_parse(e)["location"] for e in pm["pages"]}
    ins = analyse(cur_pages, gaz, known)
    print(f"[insights] strengthen={len(ins['strengthen'])} low_ctr={len(ins['low_ctr'])} "
          f"cannibalization={len(ins['cannibalization'])} geo_demand={len(ins['geo_demand'])}")

    ins["expansion"] = {"enabled": False, "added": []}
    if os.environ.get("MGR_AUTO_EXPAND", "true").lower() != "false":
        state = json.load(open(config.STATE_FILE)) if os.path.exists(config.STATE_FILE) else {"completed": []}
        max_total = int(os.environ.get("MGR_MAX_PAGES", "280"))
        pend = pending_count(pm, state)
        added = expand_pagemap(pm, gaz, ins["geo_demand"], state_performance(cur_pages, gaz), pend, max_total)
        if added:
            json.dump(pm, open(config.PAGEMAP, "w"), indent=1)
        ins["expansion"] = {"enabled": True, "pending_before": pend, "added": added,
                            "total_pages_in_map": len(pm["pages"]), "cap": max_total}
        print(f"[expand] pending={pend} -> added {len(added)}: {added}")
    json.dump(ins, open(os.path.join(DATA, "gsc_insights.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
