import os
import uuid
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

COOLDOWN_SECONDS = 1800  # 30 min
MISSION_DURATION_SECONDS = 3600  # 1 hour


def get_db():
    return psycopg2.connect(DATABASE_URL)


# =========================================================
# ROOT
# =========================================================

@app.route("/")
def home():
    return "Social Mission Engine Running"


# =========================================================
# INIT DATABASE
# =========================================================

@app.route("/init-db")
def init_db():
    conn = get_db()
    cur = conn.cursor()

    # PLAYERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id SERIAL PRIMARY KEY,
        uuid TEXT UNIQUE NOT NULL,
        username TEXT,
        total_points INTEGER DEFAULT 0,
        influence_rating INTEGER DEFAULT 1000,
        streak_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # MISSIONS (base definitions)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        base_points INTEGER NOT NULL,
        tier1_points INTEGER NOT NULL,
        tier2_points INTEGER NOT NULL,
        tier3_points INTEGER NOT NULL
    );
    """)

    # ACTIVE SESSION
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_sessions (
        id SERIAL PRIMARY KEY,
        session_id TEXT UNIQUE NOT NULL,
        player_uuid TEXT REFERENCES players(uuid) ON DELETE CASCADE,
        mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
        tier INTEGER DEFAULT 0,
        completed BOOLEAN DEFAULT FALSE,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    );
    """)

    # MISSION HISTORY
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_logs (
        id SERIAL PRIMARY KEY,
        player_uuid TEXT,
        mission_id INTEGER,
        final_tier INTEGER,
        total_points INTEGER,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Database initialized."


# =========================================================
# REGISTER PLAYER
# =========================================================

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    uuid_val = data["uuid"]
    username = data["username"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO players (uuid, username)
        VALUES (%s, %s)
        ON CONFLICT (uuid)
        DO UPDATE SET username = EXCLUDED.username
        RETURNING influence_rating, total_points;
    """, (uuid_val, username))

    result = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "rating": result[0],
        "points": result[1]
    })


# =========================================================
# ASSIGN MISSION (WITH COOLDOWN)
# =========================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():
    data = request.json
    uuid_val = data["uuid"]

    conn = get_db()
    cur = conn.cursor()

    # Check cooldown
    cur.execute("""
        SELECT completed_at FROM mission_logs
        WHERE player_uuid = %s
        ORDER BY completed_at DESC
        LIMIT 1;
    """, (uuid_val,))

    last = cur.fetchone()

    if last:
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (NOW() - %s));
        """, (last[0],))
        seconds_since = cur.fetchone()[0]

        if seconds_since < COOLDOWN_SECONDS:
            cur.close()
            conn.close()
            return jsonify({
                "error": "Cooldown active",
                "remaining": COOLDOWN_SECONDS - int(seconds_since)
            }), 400

    # Check active mission
    cur.execute("""
        SELECT id FROM mission_sessions
        WHERE player_uuid = %s
        AND completed = FALSE
        AND expires_at > NOW();
    """, (uuid_val,))

    existing = cur.fetchone()
    if existing:
        cur.close()
        conn.close()
        return jsonify({"error": "Active mission exists"}), 400

    # Pick random mission
    cur.execute("SELECT id, name FROM missions ORDER BY RANDOM() LIMIT 1;")
    mission = cur.fetchone()

    if not mission:
        cur.close()
        conn.close()
        return jsonify({"error": "No missions configured"}), 400

    mission_id, mission_name = mission

    session_id = str(uuid.uuid4())

    cur.execute("""
        INSERT INTO mission_sessions
        (session_id, player_uuid, mission_id, expires_at)
        VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour');
    """, (session_id, uuid_val, mission_id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "session_id": session_id,
        "mission_name": mission_name,
        "tier": 0,
        "expires_in": 3600
    })


# =========================================================
# COMPLETE TIER
# =========================================================

@app.route("/complete-tier", methods=["POST"])
def complete_tier():
    data = request.json
    session_id = data["session_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT mission_id, tier, player_uuid
        FROM mission_sessions
        WHERE session_id = %s
        AND completed = FALSE;
    """, (session_id,))

    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return jsonify({"error": "Invalid session"}), 400

    mission_id, tier, player_uuid = result

    if tier >= 3:
        cur.close()
        conn.close()
        return jsonify({"error": "Max tier reached"}), 400

    new_tier = tier + 1

    cur.execute("""
        UPDATE mission_sessions
        SET tier = %s
        WHERE session_id = %s;
    """, (new_tier, session_id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "new_tier": new_tier
    })


# =========================================================
# COMPLETE MISSION
# =========================================================

@app.route("/complete-mission", methods=["POST"])
def complete_mission():
    data = request.json
    session_id = data["session_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT mission_id, tier, player_uuid
        FROM mission_sessions
        WHERE session_id = %s
        AND completed = FALSE;
    """, (session_id,))

    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return jsonify({"error": "Invalid session"}), 400

    mission_id, tier, player_uuid = result

    cur.execute("""
        SELECT base_points, tier1_points, tier2_points, tier3_points
        FROM missions
        WHERE id = %s;
    """, (mission_id,))

    m = cur.fetchone()

    base, t1, t2, t3 = m

    total = base
    if tier >= 1:
        total += t1
    if tier >= 2:
        total += t2
    if tier >= 3:
        total += t3

    # Update player
    cur.execute("""
        UPDATE players
        SET total_points = total_points + %s
        WHERE uuid = %s;
    """, (total, player_uuid))

    # Mark session complete
    cur.execute("""
        UPDATE mission_sessions
        SET completed = TRUE
        WHERE session_id = %s;
    """, (session_id,))

    # Log
    cur.execute("""
        INSERT INTO mission_logs (player_uuid, mission_id, final_tier, total_points)
        VALUES (%s, %s, %s, %s);
    """, (player_uuid, mission_id, tier, total))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "final_tier": tier,
        "points_awarded": total
    })


# =========================================================
# LEADERBOARD
# =========================================================

@app.route("/leaderboard")
def leaderboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
        LIMIT 10;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {"username": r[0], "points": r[1]}
        for r in rows
    ])

@app.route("/reset-missions")
def reset_missions():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS missions CASCADE;")

    cur.execute("""
    CREATE TABLE missions (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        base_points INTEGER NOT NULL,
        tier1_points INTEGER NOT NULL,
        tier2_points INTEGER NOT NULL,
        tier3_points INTEGER NOT NULL
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Missions table reset."


@app.route("/seed-missions")
def seed_missions():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO missions (name, difficulty, base_points, tier1_points, tier2_points, tier3_points)
    VALUES
    ('Spotlight Puller', 'easy', 25, 10, 15, 25),
    ('Conversation Driver', 'medium', 50, 20, 30, 50),
    ('Social Dominator', 'hard', 100, 40, 60, 100)
    ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Missions seeded."

@app.route("/missions")
def list_missions():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, difficulty, base_points
        FROM missions
        ORDER BY difficulty;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    html = "<h1>Mission List</h1><ul>"

    for r in rows:
        html += f"<li>{r[1]} ({r[2]}) - {r[3]} base points</li>"

    html += "</ul>"

    return html

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
