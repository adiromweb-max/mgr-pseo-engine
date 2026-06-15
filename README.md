# MGR Engine — Programmatic SEO for MiniGoldenRetrievers.com

A hybrid pSEO system. The **engine runs on your infrastructure** (generates content via Claude API), and **pushes finished pages into the client's WordPress** via REST as a custom post type (`mgr_page`). Pages inherit the site's YOOtheme branding automatically.

## Architecture (where everything runs)

```
  YOUR MACHINE / SERVER                CLIENT'S WORDPRESS
  ┌─────────────────────┐             ┌──────────────────────┐
  │  run.py (Python)     │             │  mgr-pseo-pages.php   │
  │  ├ generator (Claude)│  REST API   │  ├ registers mgr_page │
  │  ├ assembler (HTML)  │ ──────────► │  ├ stores pages       │
  │  ├ pricing (live)    │  push pages │  ├ inherits YOOtheme   │
  │  └ wp_push           │             │  └ outputs SEO+schema  │
  │  YOUR Claude API key │             │  Pages live here,      │
  │  (the structural lock)│            │  owned by client       │
  └─────────────────────┘             └──────────────────────┘
```

When the retainer stops, the engine stops generating/refreshing — existing pages stay live (client owns the asset), but no new pages, no refresh, no decay protection. Structural lock, no contract needed.

## One-time setup

### 1. On the client's WordPress (you have admin + SFTP)
- Upload `wordpress-plugin/mgr-pseo-pages.php` to `wp-content/plugins/mgr-pseo-pages/` (or zip & install via admin).
- Activate **MGR pSEO Pages** in Plugins.
- Create an Application Password: Users → Profile → Application Passwords → add "MGR Engine" → copy the generated password.

### 2. On your machine/server (the engine)
```bash
cd mgr_engine
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."        # your key — stays on your side
export WP_USER="your_wp_admin_username"
export WP_APP_PASS="xxxx xxxx xxxx xxxx"      # the Application Password
```

## Running

```bash
# 1. DRY RUN — generate the quick-win pages locally (no push), review in output/
python run.py --batch quickwins

# 2. Push the quick wins to WP as DRAFTS for client review
python run.py --batch quickwins --live

# 3. After approval, roll out everything in phased batches
python run.py --batch all --live --limit 10   # rerun to continue; state tracked
```

- `DRY_RUN` writes HTML to `output/` so you can eyeball quality before anything touches the site.
- Pages push as **draft** by default — flip `PUBLISH_STATUS` to `"publish"` in `config.py` (or publish from WP) once approved.
- `generation_state.json` tracks completed pages so reruns never duplicate (anti-cannibalization safeguard).

## Phased rollout (recommended)
1. **Quick wins first** (~30 pages already ranking pos 4–20) → fastest visible movement for the first monthly report.
2. **Full cluster rollout** in batches of 10–15/day → natural indexing, no spam signal.
3. **Monthly refresh** (the retainer) → rerun to refresh content + add winning long-tail, scan for cannibalization.

## Files
- `config.py` — all settings + secrets (from env)
- `run.py` — orchestrator
- `engine/pricing.py` — live price scrape + fallback
- `engine/generator.py` — Claude content gen + RED LINE enforcement (no poodle/doodle)
- `engine/assembler.py` — JSON → branded HTML + schema
- `engine/wp_push.py` — REST push + internal-link silo resolver
- `data/` — keyword_map, pages, pagemap, data_layer
- `wordpress-plugin/` — the CPT plugin for the client's site

## Safety rails built in
- **RED LINE:** any generated content mentioning poodle/doodle is auto-rejected.
- **Anti-cannibalization:** one owner per intent; internal links always point to existing owners, never to not-yet-built pages.
- **Dynamic pricing:** never hardcoded; pulled live with a safe fallback range.
- **Dry run + draft default:** nothing goes live without your review.
