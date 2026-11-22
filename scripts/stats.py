"""Render the GitHub stats panel (assets/stats-dark.svg, assets/stats-light.svg).

In GitHub Actions it reads live numbers from the GraphQL API using GITHUB_TOKEN.
Locally (no token) it renders from scripts/stats-snapshot.json.
Standard library only.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as esc

ROOT = Path(__file__).resolve().parent.parent
LOGIN = os.getenv("GH_LOGIN", "Chaitanya697")
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace"
MINOR_LANGUAGES = {"Dockerfile", "Shell", "PowerShell", "Batchfile", "Makefile", "Procfile"}

THEMES = {
    "dark": dict(panel="#161b22", card="#0d1117", border="#30363d", text="#e6edf3", muted="#9198a1",
                 faint="#6e7681", accent="#3fb950", track="#21262d",
                 heat=["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"]),
    "light": dict(panel="#f6f8fa", card="#ffffff", border="#d1d9e0", text="#1f2328", muted="#59636e",
                  faint="#818b98", accent="#1a7f37", track="#eaeef2",
                  heat=["#eaeef2", "#9be9a8", "#40c463", "#30a14e", "#216e39"]),
}


# ---------- data
def graphql(query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } }
      }
    }
    contributionsCollection {
      contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
    }
  }
}"""

COMMITS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) { contributionsCollection(from: $from, to: $to) { totalCommitContributions } }
}"""


def streaks(days):
    """Current and longest run of consecutive days with at least one contribution."""
    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)
    current = 0
    for d in reversed(days):
        if d["contributionCount"] > 0:
            current += 1
        elif current or d is not days[-1]:   # today may still be empty
            break
    return current, longest


def live_stats():
    user = graphql(PROFILE_QUERY, {"login": LOGIN})["user"]
    created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    commits = 0
    for year in range(created.year, now.year + 1):   # the API caps each query at one year
        start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        cc = graphql(COMMITS_QUERY, {"login": LOGIN, "from": start.isoformat(), "to": end.isoformat()})
        commits += cc["user"]["contributionsCollection"]["totalCommitContributions"]

    languages = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            prev = languages.get(name, {"bytes": 0, "color": edge["node"]["color"] or "#8b949e"})
            languages[name] = {"bytes": prev["bytes"] + edge["size"], "color": prev["color"]}

    cal = user["contributionsCollection"]["contributionCalendar"]
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    current, longest = streaks(days)
    return {
        "updated": now.strftime("%Y-%m-%d"),
        "repositories": user["repositories"]["totalCount"],
        "commits": commits,
        "contributions_year": cal["totalContributions"],
        "pull_requests": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in user["repositories"]["nodes"]),
        "followers": user["followers"]["totalCount"],
        "current_streak": current,
        "longest_streak": longest,
        "languages": languages,
        "calendar": [[d["date"], d["contributionCount"]] for d in days],
    }


# ---------- drawing
def text(x, y, s, size, fill, font=SANS, weight=400, anchor="start", extra="", inner=""):
    return (f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{esc(str(s))}{inner}</text>')


def counter(x, y, value, size, fill, anchor="start", delay=0.0):
    """A number that counts up when the image loads. Viewers without SMIL see the final value."""
    if not isinstance(value, int) or value < 2:
        return text(x, y, f"{value:,}" if isinstance(value, int) else value, size, fill, SANS, 700, anchor)
    steps, dur = 12, 1.1
    total = delay + dur
    out = []
    for i in range(1, steps):
        v = round(value * (1 - (1 - i / steps) ** 3))
        t0, t1 = delay + dur * (i - 1) / steps, delay + dur * i / steps
        out.append(text(x, y, f"{v:,}", size, fill, SANS, 700, anchor, 'opacity="0"',
                        f'<set attributeName="opacity" to="1" begin="{t0:.2f}s" end="{t1:.2f}s"/>'))
    # the final value is visible by default; the animation only hides it until the count finishes
    out.append(text(x, y, f"{value:,}", size, fill, SANS, 700, anchor, "",
                    f'<set attributeName="opacity" to="0" begin="0s" end="{total - dur / steps:.2f}s"/>'))
    return "".join(out)


def card(x, y, w, h, t, label, value, sub, delay):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{t["card"]}" stroke="{t["border"]}"/>'
            f'<rect x="{x}" y="{y + 18}" width="3" height="{h - 36}" rx="1.5" fill="{t["accent"]}"/>'
            + text(x + 22, y + 32, label, 14, t["muted"], MONO, 500)
            + counter(x + 22, y + 82, value, 44, t["text"], delay=delay)
            + text(x + 22, y + 108, sub, 14, t["faint"]))


def render(stats, achievements, theme):
    t = THEMES[theme]
    W, pad = 1280, 36

    metrics = [("REPOSITORIES", stats["repositories"], "public projects"),
               ("COMMITS", stats["commits"], "all time"),
               ("CONTRIBUTIONS", stats["contributions_year"], "last 12 months")]
    langs = {k: v for k, v in stats["languages"].items() if k not in MINOR_LANGUAGES}
    metrics.append(("LANGUAGES", len(langs), "in public code"))
    # shown only once they are worth showing
    for key, label, sub in [("pull_requests", "PULL REQUESTS", "opened"), ("stars", "STARS", "earned"),
                            ("longest_streak", "LONGEST STREAK", "days in a row")]:
        if stats.get(key, 0) >= (3 if key == "longest_streak" else 1):
            metrics.append((label, stats[key], sub))
    metrics = metrics[:6]

    b = []
    y = 26
    b.append(text(pad, y + 22, f"$ gh stats --user {LOGIN}", 17, t["accent"], MONO, 600))
    b.append(text(W - pad, y + 22, f"auto-updated daily · {stats['updated']}", 13, t["faint"], MONO, 400, "end"))
    y += 44
    b.append(f'<line x1="{pad}" y1="{y}" x2="{W - pad}" y2="{y}" stroke="{t["border"]}"/>')

    # counters
    y += 24
    n, gap = len(metrics), 16
    cw = (W - 2 * pad - gap * (n - 1)) / n
    for i, (label, value, sub) in enumerate(metrics):
        b.append(card(pad + i * (cw + gap), y, cw, 128, t, label, value, sub, delay=0.15 * i))
    y += 128 + 40

    # contribution heatmap, last 53 weeks
    cal = stats.get("calendar") or []
    if cal:
        from datetime import date
        counts = {d: c for d, c in cal}
        last = date.fromisoformat(cal[-1][0])
        first = date.fromordinal(last.toordinal() - 52 * 7 - (last.weekday() + 1) % 7)
        b.append(text(pad, y, "CONTRIBUTIONS, LAST 12 MONTHS", 14, t["muted"], MONO, 500))
        b.append(text(W - pad, y, f'{sum(counts.values()):,} in total', 14, t["muted"], MONO, 500, "end"))
        y += 16
        cols, cell = 53, (W - 2 * pad) / 53
        size = cell - 4
        peak = max(counts.values() or [1]) or 1
        levels = t["heat"]
        month = None
        for i in range(cols * 7):
            day = date.fromordinal(first.toordinal() + i)
            if day > last:
                break
            col, row = divmod(i, 7)
            c = counts.get(day.isoformat(), 0)
            lvl = 0 if c == 0 else min(4, 1 + int(3 * c / peak))
            b.append(f'<rect x="{pad + col * cell:.1f}" y="{y + 18 + row * (size + 4):.1f}" width="{size:.1f}" height="{size:.1f}" rx="3" fill="{levels[lvl]}"><title>{day.isoformat()}: {c}</title></rect>')
            if row == 0 and day.month != month and day.day <= 7:
                month = day.month
                b.append(text(f"{pad + col * cell:.1f}", y + 12, day.strftime("%b"), 12, t["faint"], MONO))
        y += 18 + 7 * (size + 4) + 36

    # languages bar
    total = sum(v["bytes"] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1]["bytes"])[:6]
    rest = total - sum(v["bytes"] for _, v in top)
    parts = [(k, v["bytes"], v["color"]) for k, v in top] + ([("Other", rest, "#8b949e")] if rest / total > 0.005 else [])
    b.append(text(pad, y, "CODE BY LANGUAGE", 14, t["muted"], MONO, 500))
    y += 16
    bw, bx = W - 2 * pad, pad
    b.append(f'<clipPath id="bar"><rect x="{bx}" y="{y}" width="{bw}" height="14" rx="7"/></clipPath>')
    b.append(f'<rect x="{bx}" y="{y}" width="{bw}" height="14" rx="7" fill="{t["track"]}"/>')
    b.append('<g clip-path="url(#bar)">')
    cx = bx
    for i, (name, size, color) in enumerate(parts):
        w = bw * size / total
        b.append(f'<rect x="{cx:.1f}" y="{y}" width="{w:.1f}" height="14" fill="{color}">'
                 f'<animate attributeName="width" from="0" to="{w:.1f}" dur="0.6s" begin="{0.5 + 0.12 * i:.2f}s" fill="freeze"/></rect>')
        cx += w
    b.append('</g>')
    y += 40
    lx = pad
    for name, size, color in parts:
        label = f"{name} {100 * size / total:.1f}%"
        b.append(f'<circle cx="{lx + 6}" cy="{y - 5}" r="6" fill="{color}"/>')
        b.append(text(lx + 18, y, label, 15, t["text"], SANS, 500))
        lx += 40 + len(label) * 7.7
    y += 40

    # achievements
    b.append(text(pad, y, "ACHIEVEMENTS & CREDENTIALS", 14, t["muted"], MONO, 500))
    y += 18
    n, gap = len(achievements), 16
    aw = (W - 2 * pad - gap * (n - 1)) / n
    for i, a in enumerate(achievements):
        ax = pad + i * (aw + gap)
        b.append(f'<rect x="{ax:.1f}" y="{y}" width="{aw:.1f}" height="96" rx="10" fill="{t["card"]}" stroke="{t["border"]}"/>')
        b.append(counter(f"{ax + 20:.1f}", y + 50, a["count"], 36, t["accent"], delay=1.0 + 0.12 * i))
        b.append(text(f"{ax + 20:.1f}", y + 76, a["label"], 15, t["text"], SANS, 600))
    y += 96 + 30

    H = y
    body = (f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="14" fill="{t["panel"]}" stroke="{t["border"]}"/>'
            + "".join(b))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="GitHub statistics for {LOGIN}"><title>GitHub statistics for {LOGIN}</title>{body}</svg>\n')


def main():
    snapshot = ROOT / "scripts" / "stats-snapshot.json"
    if os.getenv("GITHUB_TOKEN"):
        stats = live_stats()
        snapshot.write_text(json.dumps(stats, indent=2) + "\n")
    else:
        stats = json.loads(snapshot.read_text())
    achievements = json.loads((ROOT / "scripts" / "achievements.json").read_text())
    for theme in THEMES:
        (ROOT / "assets" / f"stats-{theme}.svg").write_text(render(stats, achievements, theme))
    print(json.dumps({k: v for k, v in stats.items() if k != "languages"}))


if __name__ == "__main__":
    main()
