import os
import sqlite3
import uuid
import random
import time
from flask import Flask, request, jsonify, Response
import json
print("BOOTING SOCIAL MISSION ENGINE")

app = Flask(__name__)
DB_PATH = "/data/mission.db"

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
# ENSURE SCALED THRESHOLD COLUMNS EXIST
# =================================================

    cur.execute("PRAGMA table_info(mission_sessions)")
    session_columns = [row[1] for row in cur.fetchall()]

    if "scaled_min_unique" not in session_columns:
        cur.execute("ALTER TABLE mission_sessions ADD COLUMN scaled_min_unique INTEGER")

    if "scaled_min_total" not in session_columns:
        cur.execute("ALTER TABLE mission_sessions ADD COLUMN scaled_min_total INTEGER")
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
# COMPLETE MISSION (HARDENED + SERVER VALIDATION)
# =====================================================

@app.route("/complete-mission", methods=["POST"])
def complete_mission():

    data = request.get_json(silent=True) or {}

    session_id = data.get("session_id")
    unique     = int(data.get("unique", 0))
    total      = int(data.get("total", 0))

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # =================================================
    # FETCH ACTIVE SESSION
    # =================================================

    cur.execute("""
        SELECT player_uuid,
               mission_id,
               start_time,
               scaled_min_unique,
               scaled_min_total
        FROM mission_sessions
        WHERE id = ? AND completed = 0
    """, (session_id,))

    session = cur.fetchone()

    if not session:
        conn.close()
        return jsonify({"error": "Invalid or completed session"}), 400

    player_uuid = session["player_uuid"]
    mission_id  = session["mission_id"]
    start_time  = session["start_time"]
    req_unique  = session["scaled_min_unique"]
    req_total   = session["scaled_min_total"]

    now = int(time.time())
    elapsed = now - start_time

    success = True

    # =================================================
    # 1️⃣ MAX DURATION CHECK (1 hour hard limit)
    # =================================================

    if elapsed > MISSION_DURATION:
        success = False

    # =================================================
    # 2️⃣ MINIMUM DURATION CHECK (10 min anti-speedrun)
    # =================================================

    MIN_DURATION = 600  # 10 minutes

    if elapsed < MIN_DURATION:
        success = False

    # =================================================
    # 3️⃣ SERVER-SIDE THRESHOLD VALIDATION
    # =================================================

    if unique < req_unique or total < req_total:
        success = False

    # =================================================
    # FETCH MISSION DETAILS
    # =================================================

    cur.execute("""
        SELECT difficulty, base_points
        FROM missions
        WHERE id = ?
    """, (mission_id,))

    mission = cur.fetchone()

    difficulty = mission["difficulty"]
    base_points = mission["base_points"]

    # =================================================
    # APPLY REWARDS IF SUCCESS
    # =================================================

    if success:
        cur.execute("""
            UPDATE players
            SET total_points = total_points + ?
            WHERE uuid = ?
        """, (base_points, player_uuid))

    # =================================================
    # INSERT INTO HISTORY
    # =================================================

    cur.execute("""
        INSERT INTO mission_history
        (player_uuid, difficulty, success, timestamp)
        VALUES (?, ?, ?, ?)
    """, (player_uuid, difficulty, int(success), now))

    # =================================================
    # MARK SESSION COMPLETE
    # =================================================

    cur.execute("""
        UPDATE mission_sessions
        SET completed = 1,
            success = ?
        WHERE id = ?
    """, (int(success), session_id))

    conn.commit()

    # =================================================
    # RECALCULATE INFLUENCE
    # =================================================

    new_influence = recalc_influence(player_uuid)

    cur.execute("""
        UPDATE players
        SET influence = ?
        WHERE uuid = ?
    """, (new_influence, player_uuid))

    conn.commit()
    conn.close()

    title = get_title(new_influence)

    # =================================================
    # PRETTY OUTPUT
    # =================================================

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
# MISSION PRETTY ENGINE (HARDENED)
# =================================================

def progress_bar(current, required, width=10):
    if required <= 0:
        return "▒" * width

    ratio = max(0.0, min(float(current) / float(required), 1.0))
    filled = int(ratio * width)
    return "█" * filled + "▒" * (width - filled)


def build_mission_pretty(mission, session=None):

    name        = mission.get("name", "Unknown")
    difficulty  = mission.get("difficulty", "Unknown")
    category    = mission.get("category", "Unknown")
    min_unique  = mission.get("min_unique", 0)
    min_total   = mission.get("min_total", 0)
    max_per     = mission.get("max_per_avatar", 0)
    points      = mission.get("base_points", 0)
    desc        = mission.get("description", "Complete the objective.")

    unique = 0
    total  = 0
    time_left = 3600

    if session:
        unique = max(0, int(session.get("unique", 0)))
        total  = max(0, int(session.get("total", 0)))
        time_left = max(0, int(session.get("time_left", 3600)))

    unique_pct = int((unique / min_unique) * 100) if min_unique > 0 else 0
    total_pct  = int((total / min_total) * 100) if min_total > 0 else 0

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
            f"👥 Unique: {unique}/{min_unique} ({unique_pct}%) "
            f"{progress_bar(unique, min_unique)}\n"
            f"💬 Total: {total}/{min_total} ({total_pct}%) "
            f"{progress_bar(total, min_total)}\n"
            f"⏳ Time Left: {time_left} sec\n\n"
        )

    pretty += "━━━━━━━━━━━━━━━━━━━━"

    return pretty
    
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
# =====================================================
# FULL MISSION SESSION LEADERBOARD
# =====================================================

@app.route("/leaderboard/sessions")
def leaderboard_sessions():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            s.id                AS session_id,
            p.username          AS username,
            m.name              AS mission_name,
            m.category          AS category,
            m.difficulty        AS difficulty,
            m.base_points       AS base_points,
            s.start_time        AS start_time,
            s.completed         AS completed,
            s.success           AS success
        FROM mission_sessions s
        JOIN players p ON s.player_uuid = p.uuid
        JOIN missions m ON s.mission_id = m.id
        ORDER BY s.start_time DESC
        LIMIT 200
    """)

    rows = cur.fetchall()
    conn.close()

    html = """
    <html>
    <head>
        <title>Mission Sessions</title>
        <style>
            body { font-family:Arial; background:#eef2f7; padding:30px; }
            h1 { text-align:center; }
            table {
                border-collapse:collapse;
                width:100%;
                background:white;
                box-shadow:0 4px 12px rgba(0,0,0,0.1);
            }
            th, td {
                padding:10px;
                border-bottom:1px solid #ddd;
                text-align:center;
            }
            th {
                background:#111827;
                color:white;
            }
            .success { color:green; font-weight:bold; }
            .fail { color:red; font-weight:bold; }
        </style>
    </head>
    <body>
        <h1>📊 Mission Session History</h1>
        <table>
            <tr>
                <th>Player</th>
                <th>Mission</th>
                <th>Category</th>
                <th>Difficulty</th>
                <th>Points</th>
                <th>Status</th>
            </tr>
    """

    for row in rows:
        status = "⏳ Active"
        css = ""

        if row["completed"]:
            if row["success"]:
                status = "✅ Success"
                css = "success"
            else:
                status = "❌ Failed"
                css = "fail"

        html += f"""
            <tr>
                <td>{row['username']}</td>
                <td>{row['mission_name']}</td>
                <td>{row['category']}</td>
                <td>{row['difficulty']}</td>
                <td>{row['base_points']}</td>
                <td class="{css}">{status}</td>
            </tr>
        """

    html += """
        </table>
    </body>
    </html>
    """

    return html
    

# =====================================================
# GLOBAL PLAYER RANKINGS
# =====================================================

@app.route("/leaderboard/players")
def leaderboard_players():

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            uuid,
            username,
            total_points,
            influence,
            (
                SELECT COUNT(*)
                FROM mission_history h
                WHERE h.player_uuid = players.uuid
            ) AS missions_played,
            (
                SELECT COUNT(*)
                FROM mission_history h
                WHERE h.player_uuid = players.uuid
                AND h.success = 1
            ) AS missions_won
        FROM players
        ORDER BY influence DESC
        LIMIT 100
    """)

    rows = cur.fetchall()
    conn.close()

    html = """
    <html>
    <head>
        <title>Player Leaderboard</title>
        <style>
            body {
                font-family: Arial;
                background:#f4f6f9;
                padding:30px;
            }
            h1 {
                text-align:center;
            }
            table {
                border-collapse: collapse;
                width:100%;
                background:white;
                box-shadow:0 4px 12px rgba(0,0,0,0.1);
            }
            th, td {
                padding:12px;
                text-align:center;
                border-bottom:1px solid #ddd;
            }
            th {
                background:#1f2937;
                color:white;
            }
            tr:hover {
                background:#f1f1f1;
            }
            .rank {
                font-weight:bold;
            }
        </style>
    </head>
    <body>
        <h1>🏆 Global Player Rankings</h1>
        <table>
            <tr>
                <th>#</th>
                <th>Username</th>
                <th>Influence</th>
                <th>Total Points</th>
                <th>Missions Played</th>
                <th>Missions Won</th>
                <th>Win %</th>
            </tr>
    """

    for i, row in enumerate(rows, start=1):
        winrate = 0
        if row["missions_played"] > 0:
            winrate = round((row["missions_won"] / row["missions_played"]) * 100, 1)

        html += f"""
            <tr>
                <td class="rank">{i}</td>
                <td>{row['username']}</td>
                <td>{round(row['influence'],2)}</td>
                <td>{row['total_points']}</td>
                <td>{row['missions_played']}</td>
                <td>{row['missions_won']}</td>
                <td>{winrate}%</td>
            </tr>
        """

    html += """
        </table>
    </body>
    </html>
    """

    return html

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
        ("Engagement Magnet", "Ignition", "Easy", 75, 6, 12, 3),
        ("Topic Seeder", "Ignition", "Easy", 75, 7, 14, 3),
        ("Spotlight Puller", "Ignition", "Medium", 125, 8, 18, 3),
        ("Crowd Activator", "Ignition", "Medium", 125, 9, 20, 3),
        ("Question Instigator", "Ignition", "Easy", 75, 6, 14, 3),
        ("Momentum Spark", "Ignition", "Medium", 125, 8, 16, 3),
        ("Social Catalyst", "Ignition", "Hard", 250, 10, 24, 4),
        ("Echo Trigger", "Ignition", "Medium", 125, 7, 18, 4),

        ("Energy Architect", "Sustained", "Medium", 150, 10, 22, 3),
        ("Pulse Amplifier", "Sustained", "Hard", 300, 12, 30, 4),
        ("Room Stabilizer", "Sustained", "Medium", 150, 9, 20, 3),
        ("Conversation Driver", "Sustained", "Medium", 150, 10, 24, 3),
        ("Momentum Keeper", "Sustained", "Hard", 300, 12, 32, 4),
        ("Flow Controller", "Sustained", "Medium", 150, 9, 22, 3),
        ("Atmosphere Builder", "Sustained", "Medium", 150, 10, 20, 3),
        ("Activity Booster", "Sustained", "Hard", 300, 13, 35, 4),

        ("Debate Instigator", "Chain", "Hard", 350, 12, 32, 4),
        ("Rivalry Builder", "Chain", "Hard", 350, 11, 28, 4),
        ("Argument Architect", "Chain", "Hard", 500, 14, 40, 5),
        ("Conflict Catalyst", "Chain", "Hard", 500, 15, 45, 5),
    ]

    inserted = 0

    for name, category, difficulty, base_points, min_unique, min_total, max_per_avatar in missions:

        # automatic weight assignment
        if difficulty == "Easy":
            weight = 1.4
        elif difficulty == "Medium":
            weight = 1.0
        else:
            weight = 0.6

        cur.execute("""
            INSERT OR REPLACE INTO missions
            (name, category, difficulty, base_points,
             min_unique, min_total, max_per_avatar, weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name, category, difficulty, base_points,
            min_unique, min_total, max_per_avatar, weight
        ))

        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({
        "status": "Seed complete",
        "missions_processed": inserted
    })
    
@app.route("/mission/status", methods=["POST"])
def mission_status():

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    unique = int(data.get("unique", 0))
    total = int(data.get("total", 0))

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT m.*,
               s.start_time,
               s.scaled_min_unique,
               s.scaled_min_total
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

    pretty_text = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 LIVE PROGRESS\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Unique: {unique}/{mission['scaled_min_unique']} "
        f"{progress_bar(unique, mission['scaled_min_unique'])}\n"
        f"💬 Total: {total}/{mission['scaled_min_total']} "
        f"{progress_bar(total, mission['scaled_min_total'])}\n"
        f"⏳ Time Left: {time_left} sec\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({"pretty_text": pretty_text}, ensure_ascii=False),
        mimetype="application/json; charset=utf-8"
    )
    
@app.route("/health")
def health():
    return "OK", 200

# =====================================================
# START MISSION (SCALED + COOLDOWN + PRETTY)
# =====================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():

    data = request.get_json(silent=True) or {}

    uuid_val   = data.get("uuid")
    mode       = data.get("mode", "random")
    value      = data.get("value")
    population = int(data.get("population", 0))

    if not uuid_val:
        return jsonify({"error": "Missing UUID"}), 400

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # =============================
    # 1️⃣ COOLDOWN CHECK (1 hour)
    # =============================

    cur.execute("""
        SELECT start_time
        FROM mission_sessions
        WHERE player_uuid = ?
        ORDER BY start_time DESC
        LIMIT 1
    """, (uuid_val,))

    last = cur.fetchone()

    if last:
        elapsed = int(time.time()) - last["start_time"]
        if elapsed < 3600:
            conn.close()
            return jsonify({
                "error": "Cooldown active",
                "cooldown_seconds": 3600 - elapsed
            }), 429

    # =============================
    # 2️⃣ LOAD MISSIONS
    # =============================

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

    # =============================
    # 3️⃣ WEIGHTED RANDOM
    # =============================

    if len(missions) > 1:
        weights = [m["weight"] if m["weight"] else 1.0 for m in missions]
        mission = random.choices(missions, weights=weights, k=1)[0]
    else:
        mission = missions[0]

    # =============================
    # 4️⃣ POPULATION SCALING
    # =============================

    scale = 1.0

    if population >= 20:
        scale = 1.5
    elif population >= 15:
        scale = 1.35
    elif population >= 10:
        scale = 1.2
    elif population >= 5:
        scale = 1.1
    elif population <= 2:
        scale = 0.8

    min_unique = max(3, int(mission["min_unique"] * scale))
    min_total  = max(5, int(mission["min_total"] * scale))

    # =============================
    # 5️⃣ INFLUENCE SCALING
    # =============================

    cur.execute("SELECT influence FROM players WHERE uuid = ?", (uuid_val,))
    player = cur.fetchone()

    if player:
        influence = player["influence"]

        if influence > 2000:
            min_unique = int(min_unique * 1.3)
            min_total  = int(min_total * 1.3)
        elif influence > 1600:
            min_unique = int(min_unique * 1.15)
            min_total  = int(min_total * 1.15)

    # =============================
    # 6️⃣ CREATE SESSION
    # =============================

    session_id = str(uuid.uuid4())
    start_time = int(time.time())

    cur.execute("""
        INSERT INTO mission_sessions
        (id, player_uuid, mission_id, start_time,
         scaled_min_unique, scaled_min_total)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        uuid_val,
        mission["id"],
        start_time,
        min_unique,
        min_total
    ))

    conn.commit()
    conn.close()

    # =============================
    # BUILD PRETTY OUTPUT
    # =============================

    mission_dict = dict(mission)
    mission_dict["min_unique"] = min_unique
    mission_dict["min_total"]  = min_total

    session_stats = {
        "unique": 0,
        "total": 0,
        "time_left": MISSION_DURATION
    }

    pretty_text = build_mission_pretty(mission_dict, session_stats)

    return Response(
        json.dumps({
            "session_id": session_id,
            "min_unique": min_unique,
            "min_total": min_total,
            "max_per_avatar": mission["max_per_avatar"],
            "pretty_text": pretty_text
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

def auto_seed_if_empty():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ensure missions table exists
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='missions'
    """)
    table_exists = cur.fetchone()

    if not table_exists:
        conn.close()
        return

    # Check mission count
    cur.execute("SELECT COUNT(*) FROM missions")
    count = cur.fetchone()[0]
    conn.close()

    if count == 0:
        print("Auto-seeding missions...")

        # Use internal Flask test client
        with app.test_client() as client:
            client.post("/seed-missions", json={
                "secret": os.environ.get("ADMIN_SECRET", "yourStrongSecretHere"),
                "reset": False
            })
            client.post("/seed-mission-descriptions")


# =====================================================
# BOOT SEQUENCE
# =====================================================

init_db()
auto_seed_if_empty()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
