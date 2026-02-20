import os
import sqlite3
import uuid
import random
import time
from flask import Flask, request, jsonify, Response
import json
print("BOOTING SOCIAL MISSION ENGINE")

app = Flask(__name__)
DB_PATH = "mission.db"

MISSION_DURATION = 3600  # 1 hour


# =====================================================
# DATABASE INIT
# =====================================================

# =====================================================
# DATABASE INIT (FULL EXTENDED SAFE VERSION)
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # =================================================
    # PLAYERS TABLE
    # =================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        uuid TEXT PRIMARY KEY,
        username TEXT,
        total_points INTEGER DEFAULT 0,
        influence REAL DEFAULT 1000,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =================================================
    # MISSIONS TABLE (BASE STRUCTURE)
    # =================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        difficulty TEXT,
        base_points INTEGER
    )
    """)

    # =================================================
    # ADD EXTENDED COLUMNS SAFELY
    # =================================================
    cur.execute("PRAGMA table_info(missions)")
    columns = [row[1] for row in cur.fetchall()]

    # Threshold logic
    if "min_unique" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN min_unique INTEGER DEFAULT 3")

    if "min_total" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN min_total INTEGER DEFAULT 5")

    if "max_per_avatar" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN max_per_avatar INTEGER DEFAULT 3")

    # Pretty display fields
    if "description" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN description TEXT")

    if "emoji" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN emoji TEXT DEFAULT '🎯'")

    if "flavor_text" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN flavor_text TEXT")

    if "rarity" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN rarity TEXT DEFAULT 'Common'")

    if "weight" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN weight REAL DEFAULT 1.0")

    # Dynamic scoring bonuses
    if "bonus_per_unique" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN bonus_per_unique INTEGER DEFAULT 0")

    if "bonus_per_total" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN bonus_per_total INTEGER DEFAULT 0")

    if "influence_bonus" not in columns:
        cur.execute("ALTER TABLE missions ADD COLUMN influence_bonus REAL DEFAULT 0.0")

    # Ensure NULL values get defaults
    cur.execute("UPDATE missions SET min_unique = 3 WHERE min_unique IS NULL")
    cur.execute("UPDATE missions SET min_total = 5 WHERE min_total IS NULL")
    cur.execute("UPDATE missions SET max_per_avatar = 3 WHERE max_per_avatar IS NULL")
    cur.execute("UPDATE missions SET weight = 1.0 WHERE weight IS NULL")
    cur.execute("UPDATE missions SET rarity = 'Common' WHERE rarity IS NULL")
    cur.execute("UPDATE missions SET bonus_per_unique = 0 WHERE bonus_per_unique IS NULL")
    cur.execute("UPDATE missions SET bonus_per_total = 0 WHERE bonus_per_total IS NULL")
    cur.execute("UPDATE missions SET influence_bonus = 0.0 WHERE influence_bonus IS NULL")

    # =================================================
    # MISSION SESSIONS TABLE
    # =================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_sessions (
        id TEXT PRIMARY KEY,
        player_uuid TEXT,
        mission_id INTEGER,
        start_time INTEGER,
        completed INTEGER DEFAULT 0,
        success INTEGER DEFAULT 0,
        FOREIGN KEY(player_uuid) REFERENCES players(uuid)
    )
    """)

    # =================================================
    # MISSION HISTORY TABLE
    # =================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_uuid TEXT,
        difficulty TEXT,
        success INTEGER,
        timestamp INTEGER
    )
    """)

    conn.commit()
    conn.close()

# Run DB init safely
try:
    init_db()
    auto_seed_if_empty()
except Exception as e:
    print("Database init error:", e)

def auto_seed_if_empty():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure missions table exists first
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='missions'
    """)
    table_exists = cur.fetchone()

    if not table_exists:
        conn.close()
        return  # Table not ready yet

    cur.execute("SELECT COUNT(*) FROM missions")
    count = cur.fetchone()[0]
    conn.close()

    if count == 0:
        print("Auto seeding missions...")
        with app.test_client() as c:
            c.post("/seed-missions", json={
                "secret": os.environ.get("ADMIN_SECRET", "changeme"),
                "reset": False
            })
            c.post("/seed-mission-descriptions")


# =====================================================
# TITLE SYSTEM
# =====================================================

def get_title(influence):
    if influence < 500:
        return "Silent Echo"
    elif influence < 750:
        return "Static Speaker"
    elif influence < 1000:
        return "Room Participant"
    elif influence < 1200:
        return "Conversation Starter"
    elif influence < 1400:
        return "Engagement Builder"
    elif influence < 1600:
        return "Discussion Driver"
    elif influence < 1800:
        return "Social Architect"
    elif influence < 2000:
        return "Room Influencer"
    elif influence < 2200:
        return "Momentum Master"
    else:
        return "Community Influencer"


# =====================================================
# INFLUENCE CALCULATION
# =====================================================

def recalc_influence(player_uuid):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT difficulty, success
        FROM mission_history
        WHERE player_uuid = ?
        ORDER BY timestamp DESC
        LIMIT 50
    """, (player_uuid,))
    rows = cur.fetchall()

    if not rows:
        return 1000

    successes = 0
    total = len(rows)
    weight_sum = 0

    for diff, success in rows:
        weight = 1.0
        if diff == "Medium":
            weight = 1.2
        elif diff == "Hard":
            weight = 1.5

        weight_sum += weight
        if success:
            successes += 1

    sr = successes / total
    avg_weight = weight_sum / total

    influence = 1000 + (1500 * (sr - 0.5) * (avg_weight / 1.2))

    conn.close()
    return max(0, min(2500, influence))


# =====================================================
# REGISTER
# =====================================================

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    uuid_val = data.get("uuid")
    username = data.get("username")

    if not uuid_val:
        return jsonify({"error": "Missing UUID"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO players (uuid, username)
        VALUES (?, ?)
    """, (uuid_val, username))

    cur.execute("""
        UPDATE players SET username = ?
        WHERE uuid = ?
    """, (username, uuid_val))

    conn.commit()

    cur.execute("SELECT influence, total_points FROM players WHERE uuid = ?", (uuid_val,))
    row = cur.fetchone()

    conn.close()

    return jsonify({
        "influence": row[0],
        "points": row[1],
        "title": get_title(row[0])
    })


# =====================================================
# RANDOM MISSION ASSIGNMENT
# =====================================================

def get_random_mission(player_uuid):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Get last mission played
    cur.execute("""
        SELECT m.id, m.category
        FROM mission_sessions ms
        JOIN missions m ON ms.mission_id = m.id
        WHERE ms.player_uuid = ?
        ORDER BY ms.start_time DESC
        LIMIT 1
    """, (player_uuid,))
    last = cur.fetchone()

    last_id = None
    last_category = None

    if last:
        last_id = last[0]
        last_category = last[1]

    cur.execute("SELECT id, name, category, difficulty FROM missions")
    missions = cur.fetchall()

    # Filter out last mission
    if last_id:
        missions = [m for m in missions if m[0] != last_id]

    # Prevent same category twice in row
    if last_category:
        category_counts = 0
        cur.execute("""
            SELECT m.category
            FROM mission_sessions ms
            JOIN missions m ON ms.mission_id = m.id
            WHERE ms.player_uuid = ?
            ORDER BY ms.start_time DESC
            LIMIT 2
        """, (player_uuid,))
        last_two = cur.fetchall()

        if len(last_two) == 2 and last_two[0][0] == last_two[1][0]:
            missions = [m for m in missions if m[2] != last_two[0][0]]

    # Weighted random by difficulty
    weights = []
    for m in missions:
        if m[3] == "Easy":
            weights.append(0.5)
        elif m[3] == "Medium":
            weights.append(0.35)
        else:
            weights.append(0.15)

    mission = random.choices(missions, weights=weights, k=1)[0]

    conn.close()
    return mission

# =====================================================
# COMPLETE MISSION
# =====================================================

@app.route("/complete-mission", methods=["POST"])
def complete_mission():
    data = request.get_json()
    session_id = data.get("session_id")
    success = data.get("success")  # True or False

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT player_uuid, mission_id, start_time
        FROM mission_sessions
        WHERE id = ? AND completed = 0
    """, (session_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Invalid session"}), 400

    player_uuid, mission_id, start_time = row

    if int(time.time()) - start_time > MISSION_DURATION:
        success = False

    cur.execute("SELECT difficulty, base_points FROM missions WHERE id = ?", (mission_id,))
    mission = cur.fetchone()

    difficulty = mission[0]
    base_points = mission[1]

    if success:
        cur.execute("""
            UPDATE players
            SET total_points = total_points + ?
            WHERE uuid = ?
        """, (base_points, player_uuid))

    cur.execute("""
        INSERT INTO mission_history (player_uuid, difficulty, success, timestamp)
        VALUES (?, ?, ?, ?)
    """, (player_uuid, difficulty, int(success), int(time.time())))

    cur.execute("""
        UPDATE mission_sessions
        SET completed = 1, success = ?
        WHERE id = ?
    """, (int(success), session_id))

    conn.commit()

    new_influence = recalc_influence(player_uuid)

    cur.execute("""
        UPDATE players
        SET influence = ?
        WHERE uuid = ?
    """, (new_influence, player_uuid))

    conn.commit()
    conn.close()

    title = get_title(new_influence)

    pretty_text = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏁 MISSION RESULT\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{'✅ SUCCESS' if success else '❌ FAILED'}\n\n"
        f"📈 Influence: {round(new_influence,2)}\n"
        f"🏆 Title: {title}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({
            "success": success,
            "influence": new_influence,
            "title": title,
            "pretty_text": pretty_text
        }, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )

# =================================================
# MISSION PRETTY ENGINE
# =================================================

def progress_bar(current, required, width=10):
    if required <= 0:
        return "▒" * width
    ratio = min(current / required, 1.0)
    filled = int(ratio * width)
    return "█" * filled + "▒" * (width - filled)


def build_mission_pretty(mission, session=None):

    name        = mission["name"]
    difficulty  = mission["difficulty"]
    category    = mission["category"]
    min_unique  = mission["min_unique"]
    min_total   = mission["min_total"]
    max_per     = mission["max_per_avatar"]
    points      = mission["base_points"]
    desc        = mission.get("description", "Complete the objective.")

    # Live session stats (if provided)
    unique = session.get("unique", 0) if session else 0
    total  = session.get("total", 0) if session else 0
    time_left = session.get("time_left", 3600) if session else 3600

    pretty = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 SOCIAL MISSION\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 {name}\n"
        f"🔥 Difficulty: {difficulty}\n"
        f"📂 Category: {category}\n"
        f"🎯 Base Points: {points}\n\n"

        "📜 OBJECTIVE\n"
        f"{desc}\n\n"

        "📊 REQUIREMENTS\n"
        f"👥 Unique Replies: {min_unique}\n"
        f"💬 Total Replies: {min_total}\n"
        f"⚖ Max per Avatar: {max_per}\n\n"
    )

    if session:
        pretty += (
            "📈 LIVE PROGRESS\n"
            f"👥 Unique: {unique}/{min_unique} "
            f"{progress_bar(unique, min_unique)}\n"
            f"💬 Total: {total}/{min_total} "
            f"{progress_bar(total, min_total)}\n"
            f"⏳ Time Left: {int(time_left)} sec\n\n"
        )

    pretty += "━━━━━━━━━━━━━━━━━━━━"

    return pretty


    # ===============================
    # RANDOM WEIGHTING IF MULTIPLE
    # ===============================

    if len(missions) > 1:
        weights = []
        for m in missions:
            if m[3] == "Easy":
                weights.append(0.5)
            elif m[3] == "Medium":
                weights.append(0.35)
            else:
                weights.append(0.15)

        mission = random.choices(missions, weights=weights, k=1)[0]
    else:
        mission = missions[0]

    # ===============================
    # CREATE SESSION
    # ===============================

    session_id = str(uuid.uuid4())
    start_time = int(time.time())

    cur.execute("""
        INSERT INTO mission_sessions (id, player_uuid, mission_id, start_time)
        VALUES (?, ?, ?, ?)
    """, (session_id, uuid_val, mission[0], start_time))

    conn.commit()
    conn.close()

    return jsonify({
        "session_id": session_id,
        "mission_name": mission[1],
        "category": mission[2],
        "difficulty": mission[3],
        "min_unique": mission[4],
        "min_total": mission[5],
        "max_per_avatar": mission[6]
    })

# =====================================================
# SEED MISSION DESCRIPTIONS (RUN ONCE)
# =====================================================

@app.route("/seed-mission-descriptions", methods=["POST"])
def seed_mission_descriptions():

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    updates = [

        # IGNITION
        ("Engagement Magnet",
         "🎯",
         "Pull 3 unique avatars into the conversation and generate 5 total replies.",
         "Start small. Build momentum. Make the room lean in.",
         "Common", 1.0),

        ("Topic Seeder",
         "🌱",
         "Introduce a topic that sparks at least 4 unique participants and 6 total replies.",
         "Plant the idea. Let others grow it.",
         "Common", 1.0),

        ("Spotlight Puller",
         "🎤",
         "Draw focused attention from 4 different avatars and generate 8 total replies.",
         "Own the moment without begging for it.",
         "Uncommon", 1.2),

        ("Crowd Activator",
         "🔥",
         "Activate 5 unique voices and drive 9 total responses.",
         "Wake the room up.",
         "Uncommon", 1.2),

        ("Question Instigator",
         "❓",
         "Ask something that triggers 3 unique replies and 6 total messages.",
         "The right question controls everything.",
         "Common", 1.0),

        ("Momentum Spark",
         "⚡",
         "Create fast-paced interaction with 4 unique avatars and 7 total replies.",
         "Speed is power.",
         "Uncommon", 1.2),

        ("Social Catalyst",
         "🧨",
         "Cause a strong reaction from 6 unique avatars and 12 total replies.",
         "Disrupt, but stay respected.",
         "Rare", 1.5),

        ("Echo Trigger",
         "🔁",
         "Trigger repeated responses across 3 unique avatars totaling 8 replies.",
         "Make them respond again.",
         "Uncommon", 1.2),

        # SUSTAINED
        ("Energy Architect",
         "🏗",
         "Maintain steady engagement with 5 unique avatars and 10 total replies.",
         "Sustain the rhythm.",
         "Rare", 1.5),

        ("Pulse Amplifier",
         "📈",
         "Drive 6 unique voices into 14 total responses.",
         "Amplify everything.",
         "Epic", 1.8),

        ("Room Stabilizer",
         "🛡",
         "Keep interaction steady across 4 unique avatars and 9 replies.",
         "Hold the structure.",
         "Uncommon", 1.2),

        ("Conversation Driver",
         "🚗",
         "Guide 5 unique avatars into 11 total messages.",
         "You’re steering now.",
         "Rare", 1.5),

        ("Momentum Keeper",
         "🔋",
         "Sustain 6 unique participants and 15 total replies.",
         "Don’t let it die.",
         "Epic", 1.8),

        ("Flow Controller",
         "🌊",
         "Balance interaction across 5 unique avatars and 10 replies.",
         "Control the current.",
         "Rare", 1.5),

        ("Atmosphere Builder",
         "🌙",
         "Shape the mood with 6 unique voices and 9 replies.",
         "Set the emotional tone.",
         "Rare", 1.5),

        ("Activity Booster",
         "🚀",
         "Explode engagement with 7 unique avatars and 16 total replies.",
         "Push it over the edge.",
         "Epic", 2.0),

        # CHAIN
        ("Debate Instigator",
         "⚔",
         "Trigger structured disagreement from 6 unique avatars and 14 replies.",
         "Controlled conflict wins influence.",
         "Epic", 2.0),

        ("Rivalry Builder",
         "🔥",
         "Spark competitive exchange among 5 unique avatars with 12 replies.",
         "Tension creates movement.",
         "Epic", 2.0),

        ("Argument Architect",
         "🏛",
         "Construct a layered debate across 7 unique avatars and 15 replies.",
         "Build the structure of opposition.",
         "Legendary", 2.5),

        ("Conflict Catalyst",
         "💣",
         "Ignite high-intensity interaction from 8 unique avatars totaling 18 replies.",
         "Master chaos. Don’t lose control.",
         "Legendary", 2.5),
    ]

    for name, emoji, desc, flavor, rarity, weight in updates:
        cur.execute("""
            UPDATE missions
            SET emoji = ?,
                description = ?,
                flavor_text = ?,
                rarity = ?,
                weight = ?
            WHERE name = ?
        """, (emoji, desc, flavor, rarity, weight, name))

    conn.commit()
    conn.close()

    return jsonify({"status": "Mission descriptions updated"})

# =====================================================
# LEADERBOARDS
# =====================================================

@app.route("/leaderboard/points")
def leaderboard_points():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()

    return jsonify(rows)


@app.route("/leaderboard/influence")
def leaderboard_influence():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT username, influence
        FROM players
        ORDER BY influence DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()

    return jsonify(rows)

# =====================================================
# SEED MISSIONS ENDPOINT
# =====================================================

@app.route("/seed-missions", methods=["POST"])
def seed_missions():
    data = request.get_json(silent=True) or {}

    secret = data.get("secret")
    reset = data.get("reset", False)

    ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "changeme")

    if secret != ADMIN_SECRET:
        return jsonify({"error": "Unauthorized"}), 403

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if reset:
        cur.execute("DELETE FROM missions")

    missions = [

        # IGNITION
        ("Engagement Magnet", "Ignition", "Easy", 50, 3, 5, 3),
        ("Topic Seeder", "Ignition", "Easy", 50, 4, 6, 2),
        ("Spotlight Puller", "Ignition", "Medium", 100, 4, 8, 2),
        ("Crowd Activator", "Ignition", "Medium", 100, 5, 9, 2),
        ("Question Instigator", "Ignition", "Easy", 50, 3, 6, 2),
        ("Momentum Spark", "Ignition", "Medium", 100, 4, 7, 2),
        ("Social Catalyst", "Ignition", "Hard", 200, 6, 12, 2),
        ("Echo Trigger", "Ignition", "Medium", 100, 3, 8, 3),

        # SUSTAINED
        ("Energy Architect", "Sustained", "Medium", 100, 5, 10, 2),
        ("Pulse Amplifier", "Sustained", "Hard", 200, 6, 14, 2),
        ("Room Stabilizer", "Sustained", "Medium", 100, 4, 9, 2),
        ("Conversation Driver", "Sustained", "Medium", 100, 5, 11, 2),
        ("Momentum Keeper", "Sustained", "Hard", 200, 6, 15, 2),
        ("Flow Controller", "Sustained", "Medium", 100, 5, 10, 2),
        ("Atmosphere Builder", "Sustained", "Medium", 100, 6, 9, 1),
        ("Activity Booster", "Sustained", "Hard", 200, 7, 16, 2),

        # CHAIN
        ("Debate Instigator", "Chain", "Hard", 200, 6, 14, 2),
        ("Rivalry Builder", "Chain", "Hard", 200, 5, 12, 2),
        ("Argument Architect", "Chain", "Hard", 200, 7, 15, 2),
        ("Conflict Catalyst", "Chain", "Hard", 200, 8, 18, 2),
    ]

    inserted = 0

    for name, category, difficulty, base_points, min_unique, min_total, max_per_avatar in missions:
        cur.execute("""
            INSERT INTO missions 
            (name, category, difficulty, base_points, min_unique, min_total, max_per_avatar)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, category, difficulty, base_points,
              min_unique, min_total, max_per_avatar))
        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({
        "status": "Seed complete",
        "missions_inserted": inserted
    })

@app.route("/mission/status", methods=["POST"])
def mission_status():

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*, s.start_time
        FROM mission_sessions s
        JOIN missions m ON s.mission_id = m.id
        WHERE s.id = ?
    """, (session_id,))

    mission = cur.fetchone()
    conn.close()

    if not mission:
        return jsonify({"error": "Session not found"}), 404

    time_left = max(
        0,
        MISSION_DURATION - (int(time.time()) - mission["start_time"])
    )

    emoji = mission["emoji"] or "🎯"
    description = mission["description"] or "Complete the objective."
    flavor = mission["flavor_text"] or ""
    rarity = mission["rarity"] or "Common"

    pretty_text = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} {mission['name'].upper()} — STATUS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎚 Difficulty: {mission['difficulty']}\n"
        f"📂 Category: {mission['category']}\n"
        f"💎 Rarity: {rarity}\n\n"
        "🎯 OBJECTIVE\n"
        f"{description}\n\n"
        f"👥 Unique Required: {mission['min_unique']}\n"
        f"💬 Total Required: {mission['min_total']}\n"
        f"⚖ Max Per Avatar: {mission['max_per_avatar']}\n\n"
        f"⏳ Time Left: {time_left} sec\n"
        f"🏆 Base Points: {mission['base_points']}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"{flavor}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({
            "pretty_text": pretty_text,
            "text": pretty_text
        }, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )





# =====================================================
# START MISSION (CINEMATIC + PRETTY)
# =====================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():

    data = request.get_json(silent=True) or {}

    uuid_val = data.get("uuid")
    mode = data.get("mode", "random")
    value = data.get("value")

    if not uuid_val:
        return jsonify({"error": "Missing UUID"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # -----------------------------
    # LOAD MISSIONS BASED ON MODE
    # -----------------------------
    if mode == "specific" and value:
        cur.execute("SELECT * FROM missions WHERE id = ?", (value,))
    elif mode == "category" and value:
        cur.execute("SELECT * FROM missions WHERE category = ?", (value,))
    elif mode == "difficulty" and value:
        cur.execute("SELECT * FROM missions WHERE difficulty = ?", (value,))
    else:
        cur.execute("SELECT * FROM missions")

    missions = cur.fetchall()

    if not missions:
        conn.close()
        return jsonify({"error": "No missions found"}), 404

    # -----------------------------
    # WEIGHTED RANDOM
    # -----------------------------
    if len(missions) > 1:
        weights = [m["weight"] if m["weight"] else 1.0 for m in missions]
        mission = random.choices(missions, weights=weights, k=1)[0]
    else:
        mission = missions[0]

    # -----------------------------
    # CREATE SESSION
    # -----------------------------
    session_id = str(uuid.uuid4())
    start_time = int(time.time())

    cur.execute("""
        INSERT INTO mission_sessions
        (id, player_uuid, mission_id, start_time)
        VALUES (?, ?, ?, ?)
    """, (session_id, uuid_val, mission["id"], start_time))

    conn.commit()
    conn.close()
    # ==========================================
    # BUILD PRETTY USING CENTRAL ENGINE
    # ==========================================

    mission_dict = dict(mission)

    session_stats = {
        "unique": 0,
        "total": 0,
        "time_left": MISSION_DURATION
    }

    pretty_text = build_mission_pretty(mission_dict, session_stats)

    return Response(
        json.dumps({
            "session_id": session_id,
            "pretty_text": pretty_text,
            "text": pretty_text
        }, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )

@app.route("/debug-missions")
def debug_missions():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name, description FROM missions")
    rows = cur.fetchall()
    conn.close()
    return jsonify(rows)

# =====================================================
# ROOT
# =====================================================

@app.route("/")
def home():
    return "Social Mission Engine Running"


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

print("REGISTERED ROUTES:")
print(app.url_map)

