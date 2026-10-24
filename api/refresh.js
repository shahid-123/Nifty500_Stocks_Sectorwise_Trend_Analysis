const API = "https://api.github.com";
const WORKFLOW = "daily-update.yml";

function istParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
    weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts(date);
  return Object.fromEntries(parts.filter(p => p.type !== "literal").map(p => [p.type, p.value]));
}
function istDate(date = new Date()) {
  const p = istParts(date);
  return `${p.year}-${p.month}-${p.day}`;
}
function respond(res, status, body) {
  res.status(status).setHeader("Cache-Control", "no-store");
  res.status(status).json(body);
}
async function github(url, token, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "Nifty500-Sector-Intelligence",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {})
    }
  });
  if (!response.ok) throw new Error(`GitHub API HTTP ${response.status}`);
  if (response.status === 204) return {};
  return response.json();
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return respond(res, 405, { status: "method_not_allowed" });
  const now = new Date();
  const p = istParts(now);
  const today = `${p.year}-${p.month}-${p.day}`;
  const isWeekday = ["Mon", "Tue", "Wed", "Thu", "Fri"].includes(p.weekday);
  if (!isWeekday || Number(p.hour) < 16) {
    return respond(res, 200, {
      status: "not_due",
      message: "Open-site fallback checks for a missed refresh on weekdays from 4:00 PM IST onward.",
      checkedAt: now.toISOString()
    });
  }

  const updatedAt = String(req.query?.updatedAt || "").slice(0, 10);
  if (updatedAt === today) {
    return respond(res, 200, {
      status: "current", message: "Dashboard data is already updated today.", checkedAt: now.toISOString()
    });
  }

  const token = (process.env.GITHUB_TOKEN || "").trim();
  const repo = (process.env.GITHUB_REPOSITORY || "").trim().replace(/^\/+|\/+$/g, "");
  if (!token || !/^[^/]+\/[^/]+$/.test(repo)) {
    return respond(res, 503, {
      status: "not_configured",
      message: "Set GITHUB_TOKEN and GITHUB_REPOSITORY in Vercel environment variables."
    });
  }

  const base = `${API}/repos/${repo}`;
  try {
    const runsData = await github(`${base}/actions/workflows/${WORKFLOW}/runs?per_page=10`, token);
    for (const run of (runsData.workflow_runs || [])) {
      const stamp = run.run_started_at || run.created_at;
      if (stamp && istDate(new Date(stamp)) === today) {
        return respond(res, 200, {
          status: "already_started",
          message: "A refresh workflow has already started today; no duplicate was requested.",
          workflowStatus: run.status,
          checkedAt: now.toISOString()
        });
      }
    }

    await github(`${base}/actions/workflows/${WORKFLOW}/dispatches`, token, {
      method: "POST", body: JSON.stringify({ ref: "main" })
    });
    return respond(res, 202, {
      status: "dispatched",
      message: "Today's refresh had not started, so a GitHub Actions refresh has been requested.",
      checkedAt: now.toISOString()
    });
  } catch (error) {
    const message = String(error?.message || "GitHub API error").replace(/https?:\/\/\S+/g, "[URL]");
    return respond(res, 502, { status: "refresh_error", message });
  }
}
