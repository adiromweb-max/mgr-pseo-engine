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
2. NEVER mention Poodle or Doodle. This breed is NOT a poodle cross. Never imply it.
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
    """Call Claude API, return parsed content dict."""
    body = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": config.CLAUDE_MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_prompt(page, data, pricing)}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body, timeout=120,
    )
    r.raise_for_status()
    resp = r.json()
    text = "".join(b["text"] for b in resp["content"] if b["type"] == "text")

    # If the response was cut off (hit token limit), retry once at lower verbosity
    stop = resp.get("stop_reason")
    if stop == "max_tokens" and _retry:
        # ask for a more compact version to fit
        body["messages"].append({"role": "assistant", "content": text})
        body["messages"].append({"role": "user", "content":
            "Your JSON was cut off. Resend the COMPLETE valid JSON, more concise so it fits. Output ONLY the JSON."})
        r2 = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": config.ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body, timeout=120)
        r2.raise_for_status()
        text = "".join(b["text"] for b in r2.json()["content"] if b["type"] == "text")

    content = _extract_json(text)
    _validate_red_line(content)
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
