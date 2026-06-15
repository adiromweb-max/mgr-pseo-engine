"""
assembler.py — Turns generated content (JSON) into the final HTML body
that gets pushed into the WordPress CPT. The CPT inherits the YOOtheme
header/footer/colors automatically, so this only builds the inner content.
Internal links are drawn from the live keyword_map (anti-cannibalization:
never link to a page that isn't an owner; always link cluster->pillar).
"""
import json, html
import config

# Minimal scoped CSS — uses theme-neutral classes; relies on theme for base colors.
# Accent styling kept light so it blends with YOOtheme.
SCOPED_CSS = """
<style>
.mgr-wrap{max-width:880px;margin:0 auto}
.mgr-price{background:rgba(200,134,42,.08);border:1px solid rgba(200,134,42,.3);border-radius:14px;padding:24px 28px;margin:22px 0;display:flex;flex-wrap:wrap;gap:18px;align-items:center;justify-content:space-between}
.mgr-price .big{font-size:2.2rem;font-weight:700;line-height:1}
.mgr-price .lbl{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;opacity:.7;display:block;margin-top:6px}
.mgr-live{font-size:.7rem;font-weight:700;text-transform:uppercase;color:#5a8a4a}
.mgr-table{width:100%;border-collapse:collapse;margin:18px 0;border-radius:10px;overflow:hidden}
.mgr-table th{text-align:left;padding:12px 16px;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}
.mgr-table td{padding:11px 16px;border-bottom:1px solid rgba(0,0,0,.08)}
.mgr-faq details{border:1px solid rgba(0,0,0,.1);border-radius:10px;margin-bottom:10px;padding:0}
.mgr-faq summary{padding:15px 18px;cursor:pointer;font-weight:600}
.mgr-faq .a{padding:0 18px 15px}
.mgr-related{background:rgba(0,0,0,.03);border-radius:14px;padding:22px 26px;margin:28px 0}
.mgr-related ul{list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:0}
.mgr-related a{display:block;padding:10px 14px;background:#fff;border:1px solid rgba(0,0,0,.1);border-radius:8px;text-decoration:none;font-weight:600}
.mgr-cta{text-align:center;border-radius:14px;padding:34px;margin:28px 0;background:rgba(74,59,71,.06)}
.mgr-btn{display:inline-block;background:#4a3b47;color:#fff;padding:14px 36px;border-radius:50px;text-decoration:none;font-weight:700;margin-top:8px}
@media(max-width:600px){.mgr-related ul{grid-template-columns:1fr}}
</style>
"""

def _esc(s): return html.escape(str(s))

def assemble_html(content, page, data, pricing, internal_links):
    breed = data["breed"]
    parts = [SCOPED_CSS, '<div class="mgr-wrap">']

    # Intro
    parts.append(f"<p>{_esc(content['intro'])}</p>")

    # Price card (only for price/sale intents)
    if any(k in page["intent"] for k in ("price", "cost", "sale")):
        live = '<span class="mgr-live">● Live pricing from current litters</span>' if pricing["live"] else ''
        parts.append(f"""
<div class="mgr-price">
  <div><span class="big">${pricing['min']:,}–${pricing['max']:,}</span><span class="lbl">Typical all-in price</span></div>
  <div>{live}<p style="margin:6px 0 0">Adoption price ${pricing['adopt_min']:,}–${pricing['adopt_max']:,} after the $300 refundable deposit.</p></div>
</div>""")

    # Sections
    for s in content.get("sections", []):
        parts.append(f"<h2>{_esc(s['h2'])}</h2>")
        for para in s["body"].split("\n"):
            if para.strip():
                parts.append(f"<p>{_esc(para.strip())}</p>")

    # FAQ
    if content.get("faqs"):
        parts.append('<h2>Frequently Asked Questions</h2><div class="mgr-faq">')
        for f in content["faqs"]:
            parts.append(f'<details><summary>{_esc(f["q"])}</summary><div class="a">{_esc(f["a"])}</div></details>')
        parts.append('</div>')

    # Internal links (silo: cluster -> pillar + adjacent)
    if internal_links:
        parts.append('<div class="mgr-related"><h3>Related Pages</h3><ul>')
        for label, url in internal_links:
            parts.append(f'<li><a href="{_esc(url)}">{_esc(label)} →</a></li>')
        parts.append('</ul></div>')

    # CTA
    parts.append(f"""
<div class="mgr-cta">
  <h3>Ready to Find Your Mini Golden?</h3>
  <p>Apply today to join the wait list and get matched with an available puppy.</p>
  <a href="/apply/" class="mgr-btn">Apply Today</a>
  <p style="margin-top:14px">Questions? Call <a href="tel:18647943134">(864) 794-3134</a></p>
</div>""")

    parts.append('</div>')
    return "\n".join(parts)

def build_faq_schema(content):
    if not content.get("faqs"):
        return ""
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
            for f in content["faqs"]
        ],
    }, ensure_ascii=False)
