"""
pricing.py — Dynamic price resolution.
Pulls live puppy prices from the puppies page when available; falls back to
the typical range when the site is sold out ("Please check back soon").
This keeps every generated price page accurate without hardcoding numbers.
"""
import re, requests
import config

def get_live_pricing():
    """Return {'min','max','adopt_min','adopt_max','live':bool}."""
    try:
        r = requests.get(config.PRICING_SOURCE_URL, timeout=20,
                         headers={"User-Agent": "MGR-Engine/1.0"})
        r.raise_for_status()
        html = r.text
        # puppy cards show "$4200 – ( $300 deposit )" and "Price at Adoption = $3900"
        full   = [int(x) for x in re.findall(r'\$(\d{4})\s*[–-]\s*\(\s*\$300', html)]
        adopt  = [int(x) for x in re.findall(r'Adoption\s*=\s*\$(\d{4})', html)]
        if full:
            return {
                "min": min(full), "max": max(full),
                "adopt_min": min(adopt) if adopt else min(full)-300,
                "adopt_max": max(adopt) if adopt else max(full)-300,
                "live": True,
            }
    except Exception as e:
        print(f"[pricing] live fetch failed ({e}); using fallback")
    fb = config.PRICING_FALLBACK
    return {"min": fb["min"], "max": fb["max"],
            "adopt_min": fb["adopt_min"], "adopt_max": fb["adopt_max"], "live": False}

def price_range_str(p):
    return f"${p['min']:,}–${p['max']:,}"

def adopt_range_str(p):
    return f"${p['adopt_min']:,}–${p['adopt_max']:,}"

if __name__ == "__main__":
    import json
    print(json.dumps(get_live_pricing(), indent=2))
