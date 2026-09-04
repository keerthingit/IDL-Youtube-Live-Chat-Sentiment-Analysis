import pandas as pd
import os
import re
import json

# =========================================================
# Config
# =========================================================
results_dir = os.path.join("..", "results")  # raw yt-dlp .jsonl files live here
data_dir = os.path.join("..", "data")
os.makedirs(data_dir, exist_ok=True)

LIVE_CHAT_OUTPUT_PATH = os.path.join(data_dir, "yt_live_chat.csv")
ROUTINE_OUTPUT_PATH = os.path.join(data_dir, "yt_routine_live_chat.csv")
ROUTINE_DEDUPED_OUTPUT_PATH = os.path.join(data_dir, "yt_routine_live_chat_filtered.csv")
MATCH_TIMESTAMPS_PATH = os.path.join(data_dir, "yt_match_timestamps.csv")

# One raw chat file per (event_name, yt_channel) pair -- Seoul has two
# separate channel recordings, each with its own chat replay and its own
# routine timing offsets in yt_match_timestamps.csv.
#
# scraped these with yt-dlp:
# uv run yt-dlp --write-subs --sub-langs live_chat --skip-download -o "../results/sydney_steezystudio.jsonl" "https://www.youtube.com/live/dVz0G3zNYc8"
# uv run yt-dlp --write-subs --sub-langs live_chat --skip-download -o "../results/seoul_steezystudio.jsonl" "https://www.youtube.com/live/fMgoqkHVkJ8"
# uv run yt-dlp --write-subs --sub-langs live_chat --skip-download -o "../results/seoul_idl.global.jsonl" "https://www.youtube.com/live/qElhnk9wezo"
LIVE_CHAT_FILES = {
    ("Sydney", "steezystudio"): os.path.join(results_dir, "sydney_steezystudio.jsonl"),
    ("Seoul", "steezystudio"): os.path.join(results_dir, "seoul_steezystudio.jsonl"),
    ("Seoul", "idl.global"): os.path.join(results_dir, "seoul_idl.global.jsonl"),
}


# =========================================================
# Text cleanup
# =========================================================
def clean_text(s):
    """Normalize scraped text: replace non-breaking spaces with regular
    spaces and collapse repeated whitespace."""
    if s is None:
        return s
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def ms_to_hms(ms):
    """Convert a video-offset in milliseconds to an 'H:MM:SS' string,
    preserving sign for pre-stream (negative) offsets."""
    if ms is None:
        return None
    ms = int(ms)
    sign = "-" if ms < 0 else ""
    total_seconds = abs(ms) // 1000
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{h:01d}:{m:02d}:{s:02d}"


def hms_to_seconds(hms):
    """Converts an 'H:MM:SS' (optionally negative, e.g. '-0:00:30') string
    into signed total seconds. Returns None for missing/unparseable values."""
    if pd.isna(hms):
        return None
    hms = str(hms).strip()
    if not hms:
        return None
    sign = -1 if hms.startswith("-") else 1
    hms = hms.lstrip("-")
    try:
        parts = [int(p) for p in hms.split(":")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return sign * (h * 3600 + m * 60 + s)


# =========================================================
# Parse raw live_chat.jsonl (one JSON object per line)
# =========================================================
def parse_live_chat(filepath, event_name, yt_channel):
    """Parse a yt-dlp live_chat.jsonl file into a list of
    {event_name, yt_channel, timestamp, author_name, text} dicts."""
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
                    continue  # skip superchats, member events, engagement messages, etc.

                author = renderer.get("authorName", {}).get("simpleText", "Unknown")

                message_runs = renderer.get("message", {}).get("runs", [])
                text = "".join(
                    run.get("text", run.get("emoji", {}).get("shortcuts", [""])[0])
                    for run in message_runs
                )

                rows.append({
                    "event_name": event_name,
                    "yt_channel": yt_channel,
                    "timestamp": ms_to_hms(video_offset_ms),
                    "author_name": clean_text(author),
                    "text": clean_text(text),
                })
    return rows


# =========================================================
# Filter chat comments to known routine windows
# =========================================================
def filter_to_routine_windows(chat_df, match_ts_path):
    """Keeps only chat comments whose timestamp falls inside a known
    routine window (routine_start_ts to routine_end_ts) for that same
    event_name + yt_channel in yt_match_timestamps.csv, tagging each kept
    comment with the round/match/team whose window it fell into.

    Matching is scoped to event_name AND yt_channel -- not just event_name
    -- since Seoul has two different channel recordings with different
    timing offsets for the same routines. Matching on event_name alone
    would risk comparing a comment's timestamp against the wrong channel's
    routine windows.
    """
    match_ts = pd.read_csv(match_ts_path, encoding="utf-8-sig")
    match_ts["start_sec"] = match_ts["routine_start_ts"].apply(hms_to_seconds)
    match_ts["end_sec"] = match_ts["routine_end_ts"].apply(hms_to_seconds)
    match_ts["event_key"] = match_ts["event_name"].str.strip().str.lower()
    match_ts["channel_key"] = match_ts["yt_channel"].str.strip().str.lower()

    chat_df = chat_df.copy()
    chat_df["timestamp_sec"] = chat_df["timestamp"].apply(hms_to_seconds)
    chat_df["event_key"] = chat_df["event_name"].str.strip().str.lower()
    chat_df["channel_key"] = chat_df["yt_channel"].str.strip().str.lower()

    rounds, matches, teams = [], [], []
    for _, row in chat_df.iterrows():
        ts = row["timestamp_sec"]
        hit = None
        if ts is not None:
            candidates = match_ts[
                (match_ts["event_key"] == row["event_key"]) &
                (match_ts["channel_key"] == row["channel_key"])
            ]
            for _, w in candidates.iterrows():
                if w["start_sec"] is not None and w["end_sec"] is not None \
                        and w["start_sec"] <= ts <= w["end_sec"]:
                    hit = (w["round"], w["match"], w["team"])
                    break
        rounds.append(hit[0] if hit else None)
        matches.append(hit[1] if hit else None)
        teams.append(hit[2] if hit else None)

    chat_df["round"] = rounds
    chat_df["match"] = matches
    chat_df["team"] = teams

    filtered_df = chat_df[chat_df["round"].notna()].copy()
    filtered_df["round"] = filtered_df["round"].astype(int)
    filtered_df["match"] = filtered_df["match"].astype(int)

    return filtered_df[[
        "event_name", "round", "match", "team", "yt_channel",
        "timestamp", "author_name", "text",
    ]]


if __name__ == "__main__":
    # =====================================================
    # Step 1: parse raw chat files -> yt_live_chat.csv
    # =====================================================
    chat_rows = []
    for (event_name, yt_channel), chat_path in LIVE_CHAT_FILES.items():
        if os.path.exists(chat_path):
            chat_rows.extend(parse_live_chat(chat_path, event_name, yt_channel))
        else:
            print(f"WARNING: live chat file not found for {event_name} / {yt_channel}: {chat_path}")

    yt_live_chat = pd.DataFrame(
        chat_rows,
        columns=["event_name", "yt_channel", "timestamp", "author_name", "text"],
    )
    yt_live_chat.to_csv(LIVE_CHAT_OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Parsed {len(yt_live_chat)} chat comments across {len(LIVE_CHAT_FILES)} files")
    print(f"Saved: {LIVE_CHAT_OUTPUT_PATH}")

    # =====================================================
    # Step 2: filter to routine windows -> yt_routine_live_chat.csv
    # =====================================================
    yt_routine_live_chat = filter_to_routine_windows(yt_live_chat, MATCH_TIMESTAMPS_PATH)
    yt_routine_live_chat.to_csv(ROUTINE_OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nKept {len(yt_routine_live_chat)} of {len(yt_live_chat)} comments inside a routine window")
    print(f"Saved: {ROUTINE_OUTPUT_PATH}")

    # =====================================================
    # Step 3: remove duplicate comments -> yt_routine_live_chat_filtered.csv
    # =====================================================
    # dedupes on the 'text' column only -- keeps the first occurrence of
    # each exact comment text, dropping every later row with the same text
    # regardless of author, timestamp, team, etc.
    n_before = len(yt_routine_live_chat)
    yt_routine_live_chat_filtered = yt_routine_live_chat.drop_duplicates(subset=["text"])
    n_after = len(yt_routine_live_chat_filtered)
    yt_routine_live_chat_filtered.to_csv(ROUTINE_DEDUPED_OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nRemoved {n_before - n_after} duplicate-text rows ({n_after} remaining)")
    print(f"Saved: {ROUTINE_DEDUPED_OUTPUT_PATH}")