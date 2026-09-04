from playwright.sync_api import sync_playwright
from urllib.parse import urljoin
import pandas as pd
import re
import os
import json

url = "https://www.idl.pro/"


def clean_text(s):
    if s is None:
        return s
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

CATEGORY_LABELS = [
    "Choreography Complexity",
    "Staging",
    "Musicality",
    "Creativity",
    "Stylistic Athleticism",
    "Cleanliness",
    "Technical Execution + Authenticity",
    "Spacing",
    "Projection/Communication",
    "Stamina",
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url)
    page.wait_for_selector('a[data-framer-name="Pass"]', timeout=10000)

    elements = page.query_selector_all('a[data-framer-name="Pass"]')
    hrefs = list(filter(None, (el.get_attribute("href") for el in elements)))
    browser.close()

event_urls = [urljoin(url, href) for href in hrefs]

rows = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    for event_url in event_urls:
        page = browser.new_page()

        page.goto(event_url)
        page.wait_for_selector('[data-framer-name="Heading Wrap"]', timeout=15000)
        heading = page.locator('[data-framer-name="Heading Wrap"]')
        date = heading.locator('[data-framer-name="Date"] time').get_attribute("datetime")
        event_name = clean_text(heading.locator(
            '[data-framer-name="Content"] > *:not([data-framer-name="Heading Block"])'
        ).first.inner_text())
        venue = clean_text(heading.locator('[data-framer-name="Heading Block"]').inner_text())

        page.wait_for_selector('[data-framer-name="Pro Division Winner Details"]', timeout=15000)
        matches = page.locator('[data-framer-name="Tab"] > div')

        for i in range(matches.count()):
            tab = matches.nth(i)
            tab.click()
            page.wait_for_timeout(500)
            is_active = tab.locator('[data-framer-name="Active"]').count() > 0
            if not is_active:
                continue

            match_name = tab.get_attribute("name")

            teams = tab.locator('[data-framer-name="Content"] [data-framer-name="Container"]').first
            team_a = clean_text(teams.locator('[data-framer-name="Team A"] [data-framer-name="Team name"]').first.inner_text())
            team_b = clean_text(teams.locator('[data-framer-name="Team B"] [data-framer-name="Team name"]').first.inner_text())
            team_names = {"A": team_a, "B": team_b}
            team_c_loc = teams.locator('[data-framer-name="Team C"] [data-framer-name="Team name"]')
            has_team_c = team_c_loc.count() > 0
            if has_team_c:
                team_names["C"] = clean_text(team_c_loc.first.inner_text())

            fan_vote = {}
            if match_name != "Final Match":
                banner = page.locator('[data-framer-name="Banner Cells"]')
                left_team = clean_text(banner.locator(
                    '[data-framer-name="Left Content"] [data-framer-name="Team Info"] [data-framer-name="Team name"]'
                ).first.inner_text())
                left_votes = banner.locator(
                    '[data-framer-name="Left Content"] [data-framer-name="Score Wrap"] [data-framer-name="Vote Info"] [data-framer-name="Judge Title"]'
                )
                fan_vote[left_team] = {
                    "count": left_votes.nth(2).inner_text(),
                }
                right_team = clean_text(banner.locator(
                    '[data-framer-name="Left Content"] [data-framer-name="Team Info"] [data-framer-name="Team name"]'
                ).nth(1).inner_text())
                right_banner = banner.locator('[data-framer-name="Left Content"]').nth(1)
                right_votes = right_banner.locator(
                    '[data-framer-name="Score Wrap"] [data-framer-name="Vote Info"] [data-framer-name="Judge Title"]'
                )
                fan_vote[right_team] = {
                    "count": right_votes.nth(1).inner_text(),
                }
            else:
                for place in ("1ST", "2ND", "3RD"):
                    place_loc = page.locator(f'[data-framer-name="{place}"]')
                    place_team = clean_text(place_loc.locator(
                        '[data-framer-name="Title"] [data-framer-name="Team Info"] [data-framer-name="Team name"]'
                    ).inner_text())
                    place_votes = place_loc.locator(
                        '[data-framer-name="Score Wrap"] [data-framer-name="Vote Info"] [data-framer-name="Judge Title"]'
                    )
                    fan_vote[place_team] = {
                        "count": place_votes.nth(2).inner_text(),
                    }

            for j in range(1, 7):
                judge_label = f"Judges {j}"
                judge_name = clean_text(page.locator(
                    f'[data-framer-name="[OFF] {judge_label}"] [data-framer-name="Heading"] [data-framer-name="Judge Title"]'
                ).first.inner_text())

                cell_a_text = page.locator(
                    f'[data-framer-name="[OFF] {judge_label}"] [data-framer-name="Scoring"] [data-framer-name="Point Wrap"] [data-framer-name="Cell A"]'
                ).first.inner_text()
                cell_b_text = page.locator(
                    f'[data-framer-name="[OFF] {judge_label}"] [data-framer-name="Scoring"] [data-framer-name="Point Wrap"] [data-framer-name="Cell B"]'
                ).first.inner_text()

                cell_a_scores = [float(v) for v in cell_a_text.split("\n") if v.strip()]
                cell_b_scores = [float(v) for v in cell_b_text.split("\n") if v.strip()]

                cell_scores = {"A": cell_a_scores, "B": cell_b_scores}

                cell_c_loc = page.locator(
                    f'[data-framer-name="[OFF] {judge_label}"] [data-framer-name="Scoring"] [data-framer-name="Point Wrap"] [data-framer-name="Cell C"]'
                )
                if has_team_c and cell_c_loc.count() > 0:
                    cell_c_text = cell_c_loc.first.inner_text()
                    cell_scores["C"] = [float(v) for v in cell_c_text.split("\n") if v.strip()]

                for slot, scores in cell_scores.items():
                    team = team_names.get(slot)
                    if team is None:
                        continue
                    team_fan_vote = fan_vote.get(team, {"count": None})
                    for pos, score in enumerate(scores):
                        category = CATEGORY_LABELS[pos] if pos < len(CATEGORY_LABELS) else pos
                        rows.append({
                            "event": event_name,
                            "date": date,
                            "venue": venue,
                            "match": match_name,
                            "team": team,
                            "fan_vote_count": team_fan_vote["count"],
                            "judge": judge_name,
                            "category": category,
                            "score": score,
                        })

        page.close()
    browser.close()

data = pd.DataFrame(rows)

data["date"] = pd.to_datetime(data["date"]).dt.date

data["event"] = data["event"].str.lower().str.title()

def split_round_match(name):
    num = re.search(r"\d+", name)
    if num:
        return 1, int(num.group())
    return 2, 1

data[["round", "match"]] = data["match"].apply(
    lambda x: pd.Series(split_round_match(x))
)

data["fan_vote_count"] = (
    data["fan_vote_count"]
    .astype(str)
    .str.extract(r"([\d,]+)")[0]
    .str.replace(",", "", regex=False)
    .astype(int)
)

match_totals = (
    data.drop_duplicates(subset=["event", "round", "match", "team"])
    .groupby(["event", "round", "match"])["fan_vote_count"]
    .sum()
)
data["total_fan_votes"] = data.set_index(["event", "round", "match"]).index.map(match_totals)

cols = list(data.columns)
cols.remove("round")
match_idx = cols.index("match")
cols.insert(match_idx, "round")
data = data[cols]

results_dir = os.path.join("..", "results")
data_dir = os.path.join("..", "data")
os.makedirs(results_dir, exist_ok=True)
os.makedirs(data_dir, exist_ok=True)

data.to_csv(os.path.join(results_dir, "idl_scraped_data.csv"), index=False, encoding="utf-8-sig")

event_meta_data = (
    data[["event", "date", "venue"]]
    .drop_duplicates()
    .rename(columns={"event": "event_name"})
    .reset_index(drop=True)
)

VENUE_CAPACITY = {
    "Hammerstein Ballroom": 3500,
    "Thunderbird Sports Centre": 7000,
    "The Hordern Pavillion": 5500,
    "Kyung Hee University Peace Hall": 4500,
}
event_meta_data["capacity"] = event_meta_data["venue"].map(VENUE_CAPACITY)

judges_scores = (
    data[["event", "round", "match", "team", "judge", "category", "score"]]
    .rename(columns={"event": "event_name", "judge": "judge_name"})
    .reset_index(drop=True)
)

judges_match_totals = (
    judges_scores
    .groupby(["event_name", "round", "match", "team", "judge_name"], as_index=False)["score"]
    .sum()
    .rename(columns={"score": "judges_total_score"})
)

judges_match_totals["judge_point"] = (
    judges_match_totals
    .groupby(["event_name", "round", "match", "judge_name"])["judges_total_score"]
    .transform(lambda s: (s == s.max()).astype(int))
)

judges_category_averages = (
    judges_scores
    .groupby(["event_name", "round", "match", "team", "category"], as_index=False)["score"]
    .mean()
    .rename(columns={"score": "judges_category_averages"})
)
judges_category_averages["judges_category_averages"] = judges_category_averages["judges_category_averages"].round(2)

judges_match_averages_totals = (
    judges_category_averages
    .groupby(["event_name", "round", "match", "team"], as_index=False)["judges_category_averages"]
    .sum()
    .rename(columns={"judges_category_averages": "judges_match_averages"})
)
judges_match_averages_totals["judges_match_averages"] = judges_match_averages_totals["judges_match_averages"].round(2)

judges_match_averages = judges_category_averages.merge(
    judges_match_averages_totals,
    on=["event_name", "round", "match", "team"],
    how="left",
)

fan_votes = (
    data[["event", "round", "match", "team", "fan_vote_count", "total_fan_votes"]]
    .drop_duplicates(subset=["event", "round", "match", "team"])
    .rename(columns={"event": "event_name", "total_fan_votes": "total_fan_vote"})
    .reset_index(drop=True)
)

fan_votes["fan_vote_pct"] = fan_votes["fan_vote_count"] / fan_votes["total_fan_vote"]

fan_votes["fan_vote_point"] = (
    fan_votes
    .groupby(["event_name", "round", "match"])["fan_vote_count"]
    .transform(lambda s: (s == s.max()).astype(int))
)

fan_votes["fan_vote_bonus_score"] = 1 * fan_votes["fan_vote_pct"]

fan_votes = fan_votes[[
    "event_name", "round", "match", "team",
    "fan_vote_pct", "fan_vote_count", "total_fan_vote",
    "fan_vote_point", "fan_vote_bonus_score",
]]

YT_MATCH_TIMESTAMPS_RAW = [
    ("Sydney", 1, 1, "JAM REPUBLIC", "00:25:30", "00:28:24", "steezystudio"),
    ("Sydney", 1, 1, "GRV", "00:29:40", "00:32:30", "steezystudio"),
    ("Sydney", 1, 2, "QUICK STYLE", "00:48:35", "00:51:12", "steezystudio"),
    ("Sydney", 1, 2, "1MILLION", "00:52:10", "00:54:40", "steezystudio"),
    ("Sydney", 1, 3, "BROTHERHOOD", "01:14:35", "01:17:22", "steezystudio"),
    ("Sydney", 1, 3, "ROYAL FAMILY", "01:10:28", "01:13:25", "steezystudio"),
    ("Sydney", 2, 1, "BROTHERHOOD", "01:55:02", "01:57:43", "steezystudio"),
    ("Sydney", 2, 1, "GRV", "01:50:28", "01:53:00", "steezystudio"),
    ("Sydney", 2, 1, "1MILLION", "01:45:58", "01:48:38", "steezystudio"),
    ("Seoul", 1, 1, "GRV", "00:17:03", "00:20:05", "steezystudio"),
    ("Seoul", 1, 1, "ROYAL FAMILY", "00:21:06", "00:23:52", "steezystudio"),
    ("Seoul", 1, 2, "BROTHERHOOD", "00:38:47", "00:41:31", "steezystudio"),
    ("Seoul", 1, 2, "QUICK STYLE", "00:42:21", "00:45:25", "steezystudio"),
    ("Seoul", 1, 3, "JAM REPUBLIC", "01:02:42", "01:05:15", "steezystudio"),
    ("Seoul", 1, 3, "1MILLION", "00:58:55", "01:01:39", "steezystudio"),
    ("Seoul", 2, 1, "BROTHERHOOD", "01:36:50", "01:39:30", "steezystudio"),
    ("Seoul", 2, 1, "1MILLION", "01:40:50", "01:43:32", "steezystudio"),
    ("Seoul", 2, 1, "ROYAL FAMILY", "01:32:45", "01:35:30", "steezystudio"),
    ("Seoul", 1, 1, "GRV", "00:14:04", "00:17:07", "idl.global"),
    ("Seoul", 1, 1, "ROYAL FAMILY", "00:18:06", "00:20:55", "idl.global"),
    ("Seoul", 1, 2, "BROTHERHOOD", "00:35:47", "00:38:31", "idl.global"),
    ("Seoul", 1, 2, "QUICK STYLE", "00:39:21", "00:42:25", "idl.global"),
    ("Seoul", 1, 3, "JAM REPUBLIC", "00:59:42", "01:01:58", "idl.global"),
    ("Seoul", 1, 3, "1MILLION", "00:55:55", "00:58:39", "idl.global"),
    ("Seoul", 2, 1, "BROTHERHOOD", "01:33:20", "01:36:00", "idl.global"),
    ("Seoul", 2, 1, "1MILLION", "01:37:22", "01:40:00", "idl.global"),
    ("Seoul", 2, 1, "ROYAL FAMILY", "01:29:30", "01:32:15", "idl.global"),
]

yt_match_timestamps = pd.DataFrame(
    YT_MATCH_TIMESTAMPS_RAW,
    columns=["event_name", "round", "match", "team", "routine_start_ts", "routine_end_ts", "yt_channel"],
)
yt_match_timestamps["routine_start_ts"] = pd.to_datetime(
    yt_match_timestamps["routine_start_ts"], format="%H:%M:%S"
).dt.time
yt_match_timestamps["routine_end_ts"] = pd.to_datetime(
    yt_match_timestamps["routine_end_ts"], format="%H:%M:%S"
).dt.time

def ms_to_hms(ms):
    if ms is None:
        return None
    ms = int(ms)
    sign = "-" if ms < 0 else ""
    total_seconds = abs(ms) // 1000
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{h:01d}:{m:02d}:{s:02d}"


def parse_live_chat(filepath, event_name):
    rows = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            replay_action = entry.get("replayChatItemAction", {})
            video_offset_ms = replay_action.get("videoOffsetTimeMsec")
            actions = replay_action.get("actions", [])
            for action in actions:
                add_chat_item = action.get("addChatItemAction")
                if not add_chat_item:
                    continue

                renderer = add_chat_item.get("item", {}).get("liveChatTextMessageRenderer")
                if not renderer:
                    continue

                author = renderer.get("authorName", {}).get("simpleText", "Unknown")

                message_runs = renderer.get("message", {}).get("runs", [])
                text = "".join(
                    run.get("text", run.get("emoji", {}).get("shortcuts", [""])[0])
                    for run in message_runs
                )

                rows.append({
                    "event_name": event_name,
                    "timestamp": ms_to_hms(video_offset_ms),
                    "author_name": clean_text(author),
                    "text": clean_text(text),
                })
    return rows


LIVE_CHAT_FILES = {
    "Sydney": os.path.join(data_dir, "sydney_live_chat.jsonl"),
    "Seoul": os.path.join(data_dir, "seoul_live_chat.jsonl"),
}

chat_rows = []
for event_name, chat_path in LIVE_CHAT_FILES.items():
    if os.path.exists(chat_path):
        chat_rows.extend(parse_live_chat(chat_path, event_name))
    else:
        print(f"WARNING: live chat file not found for {event_name}: {chat_path}")

yt_live_chat = pd.DataFrame(chat_rows, columns=["event_name", "timestamp", "author_name", "text"])

event_meta_data.to_csv(os.path.join(data_dir, "event_meta_data.csv"), index=False, encoding="utf-8-sig")
judges_scores.to_csv(os.path.join(data_dir, "judges_scores.csv"), index=False, encoding="utf-8-sig")
judges_match_totals.to_csv(os.path.join(data_dir, "judges_match_totals.csv"), index=False, encoding="utf-8-sig")
judges_match_averages.to_csv(os.path.join(data_dir, "judges_match_averages.csv"), index=False, encoding="utf-8-sig", float_format="%.2f")
fan_votes.to_csv(os.path.join(data_dir, "fan_votes.csv"), index=False, encoding="utf-8-sig")
yt_match_timestamps.to_csv(os.path.join(data_dir, "yt_match_timestamps.csv"), index=False, encoding="utf-8-sig")
yt_live_chat.to_csv(os.path.join(data_dir, "yt_live_chat.csv"), index=False, encoding="utf-8-sig")

print(data.shape)
print(data.dtypes)
print(data.head())