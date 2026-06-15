"""
generator.py — Claude-powered unique content per page.
Each page gets a tailored prompt injecting the data layer + the specific
intent/location, with the breed RED LINE enforced. Returns structured JSON
(intro, sections, FAQ) that the assembler turns into HTML.
"""
import json, time, requests
import config

SYSTEM_PROMPT = """You are an expert dog-breed content writer for a US Mini Golden Retriever breeder (Crockett Pups, Greenville SC).

ABSOLUTE RULES — violating any is a failure:
1. A "Mini Golden Retriever" = "Golden Cavalier" = Golden Retriever x Cavalier King Charles Spaniel (95% of litters) OR Golden Retriever x Cocker Spaniel ("Golden Cocker", 5%).
2. The words "Poodle" and "Doodle" are STRICTLY FORBIDDEN anywhere in your output — not even to say "this is not a poodle", not in comparisons, not in passing, not to clarify what the breed is NOT. Do not mention poodles or doodles to contrast, exclude, or distinguish. Simply never write those words. If you feel the urge to clarify the breed is "not a poodle mix", instead just state positively what it IS (a Golden Retriever × Cavalier cross). Any appearance of "poodle" or "doodle" causes automatic rejection.
3. Use only the facts provided in the DATA block. Never invent prices, sizes, or guarantees.
4. Warm, family-first, trustworthy tone. Never clinical or salesy.
5. Write genuinely useful, specific content — no filler, no repetition across sections.
6. Output ONLY valid JSON in the exact schema requested. No markdown, no preamble.
"""

def build_user_prompt(page, data, pricing):
    breed = data["breed"]
    return f"""DATA:
Breed names: {breed['primary_name']} (aka {', '.join(breed['synonyms'][:5])})
Composition: 95% {breed['composition']['primary']['cross']}; 5% {breed['composition']['secondary']['cross']}
Size: {breed['size']['weight_lbs']['typical']} lbs typical (range {breed['size']['weight_lbs']['min']}-{breed['size']['weight_lbs']['max']}), {breed['size']['height_in']['min']}-{breed['size']['height_in']['max']} in tall, full grown at {breed['size']['full_grown_months']['min']}-{breed['size']['full_grown_months']['max']} months
Lifespan: {breed['lifespan_years']['min']}-{breed['lifespan_years']['max']} years
Colors: {', '.join(breed['coat']['colors'])}
Temperament: {', '.join(breed['temperament'])}
Price: full {pricing['min']}-{pricing['max']} USD, adoption {pricing['adopt_min']}-{pricing['adopt_max']} after $300 refundable deposit
Delivery: flat rate by region, +$200 per additional puppy; 6% SC tax only if pickup in SC
Breeder: Crockett Pups, Greenville SC, (864) 794-3134, 12-year health guarantee, genetic testing, microchipped, family-raised

PAGE TO WRITE:
Intent: {page['intent']}
{f"Location focus: {page['location']}" if page.get('location') else "Scope: national (no specific location)"}
Target keywords: {', '.join(page['keywords'][:6])}

Write JSON with this exact schema:
{{
  "title": "SEO title under 60 chars, include main keyword{' and location' if page.get('location') else ''}",
  "meta_description": "compelling meta under 155 chars",
  "h1": "page headline",
  "intro": "2-3 sentence engaging intro, specific to this intent{'/location' if page.get('location') else ''}",
  "sections": [
    {{"h2": "section heading", "body": "2-4 paragraphs of genuinely useful, specific content"}},
    {{"h2": "section heading", "body": "..."}}
  ],
  "faqs": [
    {{"q": "natural question with keyword", "a": "concise helpful answer using only the DATA facts"}}
  ]
}}
Include 2-4 sections and 3-5 FAQs. Make it unique and valuable — this page must earn its ranking."""

def generate_page_content(page, data, pricing, _retry=True):
    """Call Claude API with prompt caching, return parsed content dict."""
    # Prompt caching: the big static system prompt is cached so repeat calls are cheaper.
    body = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": config.CLAUDE_MAX_TOKENS,
        "system": [
            {"type": "text", "text": SYSTEM_PROMPT,
             "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": build_user_prompt(page, data, pricing)}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "anthropic-beta": "prompt-caching-2024-07-31",
        },
        json=body, timeout=60,
    )
    r.raise_for_status()
    resp = r.json()
    text = "".join(b["text"] for b in resp["content"] if b["type"] == "text")

    # If cut off, try ONE compact retry; never loop.
    if resp.get("stop_reason") == "max_tokens" and _retry:
        body["max_tokens"] = config.CLAUDE_MAX_TOKENS
        body["messages"] = [{"role": "user",
            "content": build_user_prompt(page, data, pricing) +
            "\n\nIMPORTANT: keep it concise — 2 sections, 3 FAQs max, so the JSON fits in one response."}]
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": config.ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01", "content-type": "application/json",
                     "anthropic-beta": "prompt-caching-2024-07-31"},
            json=body, timeout=60)
        r.raise_for_status()
        text = "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")

    content = _extract_json(text)
    # Red-line guard: if poodle/doodle slipped in, retry ONCE with a hard warning before rejecting.
    try:
        _validate_red_line(content)
    except ValueError:
        if _retry:
            warn = build_user_prompt(page, data, pricing) + (
                "\n\nCRITICAL: Your previous attempt mentioned 'poodle' or 'doodle'. "
                "Rewrite with ZERO mention of those words anywhere — not even to say it's not one. "
                "State only what the breed IS. Output ONLY the JSON.")
            r = requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": config.ANTHROPIC_API_KEY,
                         "anthropic-version": "2023-06-01", "content-type": "application/json",
                         "anthropic-beta": "prompt-caching-2024-07-31"},
                json={"model": config.CLAUDE_MODEL, "max_tokens": config.CLAUDE_MAX_TOKENS,
                      "system": [{"type": "text", "text": SYSTEM_PROMPT,
                                  "cache_control": {"type": "ephemeral"}}],
                      "messages": [{"role": "user", "content": warn}]},
                timeout=60)
            r.raise_for_status()
            text = "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")
            content = _extract_json(text)
        _validate_red_line(content)  # if still bad, this raises and the page is skipped
    return content

def _extract_json(text):
    """Robustly extract a JSON object from model output."""
    text = text.strip()
    # strip code fences
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        text = text.removeprefix("json").strip().strip("`").strip()
    # grab from first { to last }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end+1]
    return json.loads(text)

def _validate_red_line(content):
    """Hard guard: reject any output that mentions poodle/doodle."""
    blob = json.dumps(content).lower()
    for banned in ("poodle", "doodle"):
        if banned in blob:
            raise ValueError(f"RED LINE VIOLATION: output contained '{banned}' — page rejected")

if __name__ == "__main__":
    print("generator module — import and call generate_page_content()")
