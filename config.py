"""
MGR Engine — Configuration
Programmatic SEO engine for MiniGoldenRetrievers.com
Runs on Adi's infrastructure. Generates content via Claude API, pushes to WordPress via REST.
"""
import os

# ── Claude API (Adi's key — structural lock lives here) ──────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # set in env, never hardcode
CLAUDE_MODEL      = "claude-sonnet-4-6"      # content generation
CLAUDE_MAX_TOKENS = 4000

# ── WordPress REST API (client's site) ──────────────────────────────
WP_BASE_URL   = "https://www.minigoldenretrievers.com"
WP_API        = f"{WP_BASE_URL}/wp-json/wp/v2"
WP_USER       = os.environ.get("WP_USER", "")            # application-password user
WP_APP_PASS   = os.environ.get("WP_APP_PASS", "")        # WP Application Password
WP_CPT_SLUG   = "mgr_page"                                # custom post type
WP_CPT_REST   = f"{WP_BASE_URL}/wp-json/wp/v2/{WP_CPT_SLUG}"

# ── Live pricing source (dynamic, with fallback) ────────────────────
PRICING_SOURCE_URL = f"{WP_BASE_URL}/mini-golden-retriever-puppies/"
PRICING_FALLBACK   = {"min": 3900, "max": 4300, "adopt_min": 3900, "adopt_max": 4000}

# ── Generation controls ─────────────────────────────────────────────
BATCH_SIZE        = 10          # pages per run (phased rollout, avoid spam signals)
MAX_WORKERS       = 4           # how many pages to generate in parallel (speed)
PUBLISH_STATUS    = "publish"   # 'draft' for review, 'publish' when approved
DRY_RUN           = False        # True = generate HTML locally only, don't push to WP
REQUEST_DELAY_SEC = 2           # politeness delay between API calls

# ── Paths ────────────────────────────────────────────────────────────
BASE          = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE, "data")
OUTPUT_DIR    = os.path.join(BASE, "output")
LOG_DIR       = os.path.join(BASE, "logs")
DATA_LAYER    = os.path.join(DATA_DIR, "data_layer.json")
PAGEMAP       = os.path.join(DATA_DIR, "final_pagemap.json")
KEYWORD_MAP   = os.path.join(DATA_DIR, "keyword_map.json")
STATE_FILE    = os.path.join(DATA_DIR, "generation_state.json")  # tracks what's built (anti-dup + anti-cannibal)

    
