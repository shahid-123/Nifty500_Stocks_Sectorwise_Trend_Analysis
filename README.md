# Nifty 500 Sector Intelligence — GitHub + Vercel deployment

This project builds a static, interactive HTML sector dashboard from Yahoo Finance daily prices. GitHub Actions refreshes the dashboard on weekdays, and Vercel hosts it. A small Vercel API endpoint can request a fallback refresh when a visitor opens stale dashboard data after 4:00 PM IST.

## What runs and when

- **Scheduled refresh:** Monday–Friday at **4:00 PM India Standard Time** (`16:00 Asia/Kolkata`) through GitHub Actions. GitHub may delay scheduled workflows during heavy load; the time is not guaranteed to start at the exact minute.
- **Open-dashboard fallback:** On opening the site, the page calls `/api/refresh`. The endpoint requests a workflow run only if it is a weekday after 4:00 PM IST, the embedded dashboard data is not dated today, and no workflow run has already started that day. The endpoint is a lightweight Node.js function; it does not run the full Python updater itself.
- **Publish:** When the workflow commits refreshed files in `Output/`, the connected Vercel project redeploys from GitHub. Deployment and data refresh take several minutes; a browser already open may need a refresh to see the new version.
- **Data:** Yahoo Finance (`yfinance`) availability and rate limits can vary. Individual symbols may fail. The dashboard is an analytical screener, not financial advice.

## 1. Create and push the GitHub repository

1. On GitHub, create an **empty private or public repository** named `nifty500-sector-intelligence` (do not initialize it with a README or license).
2. Extract this ZIP into a permanent folder. Open Command Prompt in that folder.
3. Run these commands, replacing `YOUR_GITHUB_USERNAME` with your username:

```bat
git init
git add .
git commit -m "Initial Nifty 500 Sector Intelligence dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/nifty500-sector-intelligence.git
git push -u origin main
```

If Git says a remote already exists, use `git remote set-url origin https://github.com/YOUR_GITHUB_USERNAME/nifty500-sector-intelligence.git` instead of adding it. Sign in to GitHub when Git prompts you. Do not put passwords or tokens in the remote URL.

## 2. Enable GitHub Actions write permission

In the repository, open **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and save. The workflow commits refreshed files back to `main`.

For the first run, open **Actions → Daily Nifty 500 data refresh → Run workflow**. Wait for it to finish successfully. The updater attempts to download the official Nifty 500 constituent list if `Input/nifty500_stocks.csv` has fewer than 400 rows.

## 3. Deploy to Vercel

1. Sign in to Vercel and select **Add New → Project → Import Git Repository**.
2. Select the GitHub repository. Framework preset: **Other**. Output directory: **`Output`**. Leave the build command empty.
3. Before deploying, open **Project Settings → Environment Variables** and add the two variables below for **Production** (Preview optional):
   - `GITHUB_REPOSITORY` = `YOUR_GITHUB_USERNAME/nifty500-sector-intelligence`
   - `GITHUB_TOKEN` = a GitHub fine-grained personal access token with **Actions: Read and write** permission for this repository. The workflow itself also needs repository **Contents: Read and write** permission as described above.
4. Deploy. If you deployed before setting variables, redeploy after adding them.

Keep `GITHUB_TOKEN` only in Vercel's server-side environment variables. Never place it in HTML, JavaScript, the repository, or a screenshot. The token is only used by `/api/refresh` to check workflow status and dispatch a workflow.

## 4. Verify it

- Check **GitHub → Actions** and confirm the first `Daily Nifty 500 data refresh` run completes.
- After a successful run, `Output/index.html`, `Output/last_update.json`, and the generated CSV/JSON files should be committed. Vercel should redeploy automatically from the new commit.
- Open the deployed site and check the refresh-status line near the bottom. It should explain whether the dashboard is current or a fallback refresh was requested.
- To test the fallback without waiting until the next weekday, manually run the workflow from GitHub Actions. The API intentionally only requests fallback refreshes on weekdays from 4:00 PM IST onward.

## 5. Local Windows usage remains available

Run `run_update_and_open.bat` to install dependencies, refresh data and open `Output/index.html`. This local BAT process is independent of the Vercel-hosted app. If you want a separate local daily schedule, configure Windows Task Scheduler to run `run_update_silent.bat`.

## Important limitations

- GitHub Actions scheduled jobs can start late; 4:00 PM IST is the requested schedule, not a guaranteed exact execution time.
- The browser-open fallback only works after the Vercel project is deployed with `GITHUB_REPOSITORY` and `GITHUB_TOKEN` correctly configured.
- The fallback checks for a run that has started that day to avoid duplicate requests; if that day's run fails, inspect the Actions log and use **Run workflow** to retry.
- Sector composites are equal-weighted proxies based on the provided constituent-sector labels, not official NSE sector indices.


## Website + mobile app (PWA)
This project includes a Progressive Web App manifest, app icons, and a service worker. Deploy it over HTTPS (Vercel provides HTTPS), then open the website on your phone and choose **Add to Home Screen** (Android/Chrome) or **Add to Home Screen** from the iOS Safari share menu. The dashboard uses network-first loading for HTML so newly deployed data is preferred; offline use is limited to the cached app shell / last cached page and does not refresh market data.

## Daily schedule
GitHub Actions is scheduled for `30 10 * * 1-5` UTC, which corresponds to 4:00 PM India Standard Time Monday through Friday. GitHub scheduled jobs can start late. You can also run the workflow manually from the repository's **Actions** tab. The on-open fallback only requests an update when the deployed dashboard is stale after the scheduled time; the Vercel endpoint requires the GitHub repository and token environment variables configured in Vercel.

## Deploy notes
- Keep the GitHub token only in Vercel Environment Variables; never commit it.
- The repository workflow writes refreshed output files back to the `main` branch, which can trigger a Vercel redeployment when the project is connected to GitHub.
- Verify the first workflow run, the deployed dashboard, and the refresh endpoint before relying on automation.
