# MGR Engine — GitHub Actions Setup (runs in the cloud, no local Python)

This runs the whole pSEO engine on GitHub's servers. No Python on your computer. You push the code once, add 3 secrets, and click Run. It generates pages and pushes them into the client's WordPress.

---

## STEP 1 — Create the repository (one time)

1. Go to https://github.com/new
2. Repository name: `mgr-pseo-engine`
3. Set it to **Private** (your code, your client's data)
4. Do NOT add a README (we have one)
5. Click **Create repository**

## STEP 2 — Upload the files

Easiest way (no git install needed):
1. On the new empty repo page, click **"uploading an existing file"** link.
2. Drag the ENTIRE contents of this `mgr_engine` folder into the browser.
   - IMPORTANT: drag the files/folders INSIDE `mgr_engine` (config.py, run.py, engine/, data/, .github/, etc.), not the `mgr_engine` folder itself.
   - Make sure the hidden `.github` folder uploads too (it holds the workflow). If drag-drop skips it, use git (Step 2-alt).
3. Click **Commit changes**.

Step 2-alt (if you prefer git, on any machine with git):
```
cd mgr_engine
git init
git add .
git commit -m "MGR pSEO engine"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/mgr-pseo-engine.git
git push -u origin main
```

## STEP 3 — Add your secrets (the API key + WP login)

1. In the repo: **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add these three, one at a time:

| Name | Value |
|------|-------|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key |
| `WP_USER` | your WordPress admin username |
| `WP_APP_PASS` | the WordPress Application Password (with spaces) |

Secrets are encrypted — they never show in logs or code.

## STEP 4 — Run it

1. Go to the **Actions** tab in your repo.
2. Click **MGR pSEO Engine** on the left.
3. Click **Run workflow** (button on the right).
4. Choose:
   - **batch:** `quickwins` (start here)
   - **live:** leave UNCHECKED for the first run (dry run — generates files only, doesn't touch the site)
   - **limit:** `15`
5. Click the green **Run workflow**.

Watch it run (refresh the page). Green check = success.

## STEP 5 — Review the generated pages

1. Click the finished run.
2. Scroll to **Artifacts** at the bottom → download **generated-pages**.
3. Unzip, open any `.html` in your browser. Check quality, branding, accuracy.

## STEP 6 — Push to WordPress for real

When you're happy with the dry-run quality:
1. **Run workflow** again
2. batch: `quickwins`, **live: CHECKED**, limit: `15`
3. Pages push into WordPress as **drafts** (CPT "MGR Pages") for final review.
4. Review in WP, then publish.

## STEP 7 — Roll out everything

Once quick wins look good live:
- **Run workflow** → batch: `all`, live: CHECKED, limit: `15` (rerun daily to phase in naturally).

## Automatic monthly refresh (the retainer)
The workflow is scheduled to run on the 1st of every month automatically (full refresh, live). This is your recurring value — it keeps pages fresh, adds winning long-tail, and protects against decay, with zero manual work.

---

## Reminder: the WordPress plugin
Before pushing live, make sure `wordpress-plugin/mgr-pseo-pages.zip` is installed and active on the client's site (you already did this). It registers the CPT the engine pushes into.
