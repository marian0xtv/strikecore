#!/usr/bin/env python3
"""
StrikeCore: Instagram Deep Social Circle Profiler v2
Analyzes: followers, following, mutuals, post comments, likes, tags, mentions.
Ranks connections by interaction frequency.
"""
import json, os, subprocess, sys, time, re
from datetime import datetime
from collections import Counter

USERNAME = sys.argv[1] if len(sys.argv) > 1 else "luigisav"
SESSION = open(os.path.expanduser("~/.strikecore/ig_session")).read().strip()
OUTPUT = "/home/atlas/argus-intelligence/strikecore/" + USERNAME + "_deep_social.txt"

def api(endpoint):
    cmd = ["curl", "-s",
           "https://i.instagram.com/api/v1/" + endpoint,
           "-H", "User-Agent: Instagram 275.0.0.27.98 Android (30/11; 420dpi; 1080x2280; samsung; SM-G991B)",
           "-H", "X-IG-App-ID: 936619743392459",
           "-H", "Cookie: sessionid=" + SESSION]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try:
        return json.loads(r.stdout)
    except:
        return None

lines = []
def log(text):
    print(text)
    lines.append(text)

# Interaction tracking
interactions = Counter()  # username -> total interaction score
interaction_details = {}  # username -> {type: count}

def track(username, full_name, interaction_type):
    if not username or username == USERNAME:
        return
    interactions[username] += 1
    if username not in interaction_details:
        interaction_details[username] = {"full_name": full_name, "types": Counter()}
    interaction_details[username]["types"][interaction_type] += 1
    if full_name and not interaction_details[username]["full_name"]:
        interaction_details[username]["full_name"] = full_name

log("=" * 70)
log("  STRIKECORE — INSTAGRAM DEEP SOCIAL PROFILER")
log("  Target: @" + USERNAME)
log("  Date: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
log("=" * 70)

# ── 1. Profile ──
log("\n[1] FETCHING PROFILE...")
profile = api("users/web_profile_info/?username=" + USERNAME)
user = profile.get("data", {}).get("user", {}) if profile else {}
if not user:
    log("ERROR: Cannot fetch profile")
    sys.exit(1)

user_id = user.get("id", "")
log("  Name: " + str(user.get("full_name", "")))
log("  ID: " + str(user_id))
log("  Followers: " + str(user.get("edge_followed_by", {}).get("count", 0)))
log("  Following: " + str(user.get("edge_follow", {}).get("count", 0)))
log("  Posts: " + str(user.get("edge_owner_to_timeline_media", {}).get("count", 0)))

# ── 2. Followers (paginated, up to 100) ──
log("\n[2] FETCHING FOLLOWERS...")
all_followers = {}
next_cursor = ""
for page in range(4):  # 4 pages x 25 = up to 100
    endpoint = "friendships/" + str(user_id) + "/followers/?count=25"
    if next_cursor:
        endpoint += "&max_id=" + next_cursor
    data = api(endpoint)
    if not data or "users" not in data:
        break
    for f in data["users"]:
        uname = f.get("username", "")
        all_followers[uname] = f.get("full_name", "")
    next_cursor = data.get("next_max_id", "")
    log("  Page " + str(page+1) + ": " + str(len(data["users"])) + " followers (total: " + str(len(all_followers)) + ")")
    if not next_cursor:
        break
    time.sleep(1)

# ── 3. Following (paginated, up to 100) ──
log("\n[3] FETCHING FOLLOWING...")
all_following = {}
next_cursor = ""
for page in range(4):
    endpoint = "friendships/" + str(user_id) + "/following/?count=25"
    if next_cursor:
        endpoint += "&max_id=" + next_cursor
    data = api(endpoint)
    if not data or "users" not in data:
        break
    for f in data["users"]:
        uname = f.get("username", "")
        all_following[uname] = f.get("full_name", "")
    next_cursor = data.get("next_max_id", "")
    log("  Page " + str(page+1) + ": " + str(len(data["users"])) + " following (total: " + str(len(all_following)) + ")")
    if not next_cursor:
        break
    time.sleep(1)

# ── 4. Mutuals ──
log("\n[4] MUTUAL CONNECTIONS (inner circle)")
mutuals = set(all_followers.keys()) & set(all_following.keys())
for m in sorted(mutuals):
    name = all_followers.get(m, "") or all_following.get(m, "")
    track(m, name, "mutual")
    log("  MUTUAL: @" + m + " — " + name)
log("  Total mutuals: " + str(len(mutuals)))

# ── 5. Fetch user media (posts) for deep analysis ──
log("\n[5] FETCHING POSTS FOR DEEP ANALYSIS...")
media_data = api("feed/user/" + str(user_id) + "/?count=30")
posts = media_data.get("items", []) if media_data else []
log("  Posts fetched: " + str(len(posts)))

all_locations = []
all_commenters = Counter()

for i, post in enumerate(posts):
    post_id = post.get("pk", "")
    ts = post.get("taken_at", 0)
    date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
    
    # Location
    loc = post.get("location")
    if loc:
        loc_name = loc.get("name", "")
        loc_city = loc.get("city", "")
        loc_str = loc_name + (" (" + loc_city + ")" if loc_city else "")
        all_locations.append(loc_str)
        log("  POST " + str(i+1) + " [" + date_str + "] LOCATION: " + loc_str)
    
    # Tagged users (usertags)
    usertags = post.get("usertags", {}).get("in", [])
    for tag in usertags:
        tu = tag.get("user", {})
        uname = tu.get("username", "")
        fname = tu.get("full_name", "")
        track(uname, fname, "tagged_in_post")
        log("  POST " + str(i+1) + " [" + date_str + "] TAGGED: @" + uname + " — " + fname)
    
    # Caption mentions
    caption = post.get("caption", {})
    if caption:
        text = caption.get("text", "")
        mentions = re.findall(r'@([a-zA-Z0-9_.]+)', text)
        for m in mentions:
            if m != USERNAME:
                fname = all_followers.get(m, all_following.get(m, ""))
                track(m, fname, "mentioned_in_caption")
                log("  POST " + str(i+1) + " [" + date_str + "] MENTION: @" + m)
    
    # Fetch comments for this post
    if post_id:
        comments_data = api("media/" + str(post_id) + "/comments/?count=30")
        comments = comments_data.get("comments", []) if comments_data else []
        for comment in comments:
            cu = comment.get("user", {})
            cuname = cu.get("username", "")
            cfname = cu.get("full_name", "")
            ctext = comment.get("text", "")[:80]
            if cuname and cuname != USERNAME:
                track(cuname, cfname, "commented")
                all_commenters[cuname] += 1
        if comments:
            log("  POST " + str(i+1) + " [" + date_str + "] COMMENTS: " + str(len(comments)) + " (from " + str(len(set(c.get("user",{}).get("username","") for c in comments))) + " unique users)")
        time.sleep(0.5)

    # Fetch likers for this post (top likers)
    if post_id:
        likers_data = api("media/" + str(post_id) + "/likers/")
        likers = likers_data.get("users", []) if likers_data else []
        for liker in likers[:30]:
            luname = liker.get("username", "")
            lfname = liker.get("full_name", "")
            if luname and luname != USERNAME:
                track(luname, lfname, "liked")
        if likers:
            log("  POST " + str(i+1) + " [" + date_str + "] LIKES: " + str(len(likers)) + " users")
        time.sleep(0.5)

# ── 6. Ranked connections ──
log("\n" + "=" * 70)
log("  RANKED SOCIAL CONNECTIONS (by interaction strength)")
log("=" * 70)

for rank, (uname, score) in enumerate(interactions.most_common(30), 1):
    details = interaction_details.get(uname, {})
    fname = details.get("full_name", "")
    types = details.get("types", {})
    types_str = ", ".join(t + ":" + str(c) for t, c in types.most_common())
    is_mutual = "MUTUAL" if uname in mutuals else ""
    log("  " + str(rank).rjust(2) + ". @" + uname + " — " + fname)
    log("      Score: " + str(score) + " | " + types_str + " " + is_mutual)

# ── 7. Top commenters ──
log("\n" + "-" * 50)
log("  TOP COMMENTERS (most active on target's posts)")
log("-" * 50)
for uname, count in all_commenters.most_common(15):
    fname = interaction_details.get(uname, {}).get("full_name", "")
    mutual_tag = " [MUTUAL]" if uname in mutuals else ""
    log("  @" + uname + " — " + fname + " (" + str(count) + " comments)" + mutual_tag)

# ── 8. Locations ──
log("\n" + "-" * 50)
log("  LOCATIONS FREQUENTED")
log("-" * 50)
loc_counts = Counter(all_locations)
for loc, count in loc_counts.most_common(10):
    log("  " + loc + " (" + str(count) + " posts)")
if not loc_counts:
    log("  No geotagged posts found")

# ── 9. Possible family (same surname) ──
log("\n" + "-" * 50)
log("  POSSIBLE FAMILY (same surname in network)")
log("-" * 50)
target_surname = user.get("full_name", "").split()[-1].lower() if user.get("full_name") else ""
if target_surname:
    for uname in set(list(all_followers.keys()) + list(all_following.keys())):
        fname = all_followers.get(uname, "") or all_following.get(uname, "")
        if fname and target_surname in fname.lower().split():
            mutual_tag = " [MUTUAL]" if uname in mutuals else ""
            log("  @" + uname + " — " + fname + mutual_tag)

# ── 10. Summary ──
log("\n" + "=" * 70)
log("  SUMMARY")
log("=" * 70)
log("  Followers analyzed: " + str(len(all_followers)))
log("  Following analyzed: " + str(len(all_following)))
log("  Mutual connections: " + str(len(mutuals)))
log("  Posts analyzed: " + str(len(posts)))
log("  Unique interactors: " + str(len(interactions)))
log("  Locations found: " + str(len(loc_counts)))
log("  Top connection: @" + (interactions.most_common(1)[0][0] if interactions else "none"))
log("=" * 70)

with open(OUTPUT, "w") as f:
    f.write("\n".join(lines))
print("\nSaved: " + OUTPUT)
