import os
import sqlite3
import uuid
import random
import time
from flask import Flask, request, jsonify

app = Flask(__name__)
DB_PATH = "mission.db"

MISSION_DURATION = 3600  # 1 hour


# =====================================================
# DATABASE INIT
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        uuid TEXT PRIMARY KEY,
        username TEXT,
        total_points INTEGER DEFAULT 0,
        influence REAL DEFAULT 1000,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        difficulty TEXT,
        base_points INTEGER
)

    """)

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


init_db()


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

    return jsonify({
        "success": success,
        "influence": new_influence,
        "title": get_title(new_influence)
    })

# =====================================================
# START MISSION
# =====================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():
    data = request.get_json()
    uuid_val = data.get("uuid")

    if not uuid_val:
        return jsonify({"error": "Missing UUID"}), 400

    mission = get_random_mission(uuid_val)

    if not mission:
        return jsonify({"error": "No missions available"}), 500

    session_id = str(uuid.uuid4())
    start_time = int(time.time())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

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
        "difficulty": mission[3]
    })

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
        ("Engagement Magnet", "Ignition", "Easy", 50),
        ("Topic Seeder", "Ignition", "Easy", 50),
        ("Spotlight Puller", "Ignition", "Medium", 100),
        ("Crowd Activator", "Ignition", "Medium", 100),
        ("Question Instigator", "Ignition", "Easy", 50),
        ("Momentum Spark", "Ignition", "Medium", 100),
        ("Social Catalyst", "Ignition", "Hard", 200),
        ("Echo Trigger", "Ignition", "Medium", 100),

        # SUSTAINED
        ("Energy Architect", "Sustained", "Medium", 100),
        ("Pulse Amplifier", "Sustained", "Hard", 200),
        ("Room Stabilizer", "Sustained", "Medium", 100),
        ("Conversation Driver", "Sustained", "Medium", 100),
        ("Momentum Keeper", "Sustained", "Hard", 200),
        ("Flow Controller", "Sustained", "Medium", 100),
        ("Atmosphere Builder", "Sustained", "Medium", 100),
        ("Activity Booster", "Sustained", "Hard", 200),

        # CHAIN
        ("Debate Instigator", "Chain", "Hard", 200),
        ("Rivalry Builder", "Chain", "Hard", 200),
        ("Argument Architect", "Chain", "Hard", 200),
        ("Conflict Catalyst", "Chain", "Hard", 200),
    ]

    inserted = 0

    for name, category, difficulty, base_points in missions:
        cur.execute("""
            INSERT INTO missions (name, category, difficulty, base_points)
            VALUES (?, ?, ?, ?)
        """, (name, category, difficulty, base_points))
        inserted += 1

    conn.commit()
    conn.close()

    return jsonify({
        "status": "Seed complete",
        "missions_inserted": inserted
    })


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
