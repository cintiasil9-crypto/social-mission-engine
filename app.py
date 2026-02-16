import os
import uuid
import psycopg2
from flask import Flask, request, jsonify, Response
import json

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

COOLDOWN_SECONDS = 1800
MISSION_DURATION = 3600


# =====================================================
# DB CONNECTION
# =====================================================

def get_db():
    return psycopg2.connect(DATABASE_URL)


# =====================================================
# ROOT
# =====================================================

@app.route("/")
def home():
    return "🚀 Social Mission Engine Live"


# =====================================================
# INIT DATABASE
# =====================================================

@app.route("/init-db")
def init_db():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id SERIAL PRIMARY KEY,
        uuid TEXT UNIQUE NOT NULL,
        username TEXT,
        total_points INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        description TEXT NOT NULL,
        tier1_required INTEGER NOT NULL,
        tier2_required INTEGER NOT NULL,
        tier3_required INTEGER NOT NULL,
        base_points INTEGER NOT NULL,
        tier1_points INTEGER NOT NULL,
        tier2_points INTEGER NOT NULL,
        tier3_points INTEGER NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_sessions (
        id SERIAL PRIMARY KEY,
        session_id TEXT UNIQUE NOT NULL,
        player_uuid TEXT,
        mission_id INTEGER,
        tier INTEGER DEFAULT 0,
        progress INTEGER DEFAULT 0,
        completed BOOLEAN DEFAULT FALSE,
        expires_at TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "✅ Database initialized."


# =====================================================
# SEED MISSIONS
# =====================================================

@app.route("/seed-missions")
def seed_missions():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO missions (
        name, difficulty, description,
        tier1_required, tier2_required, tier3_required,
        base_points, tier1_points, tier2_points, tier3_points
    )
    VALUES
    (
        'Spotlight Puller',
        'easy',
        'Pull attention and get replies from different avatars.',
        1, 3, 5,
        25, 10, 15, 25
    ),
    (
        'Conversation Driver',
        'medium',
        'Start and sustain conversation from multiple avatars.',
        3, 6, 10,
        50, 20, 30, 50
    ),
    (
        'Social Dominator',
        'hard',
        'Dominate the room socially and create heavy engagement.',
        5, 10, 20,
        100, 40, 60, 100
    )
    ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "🔥 Missions seeded."


# =====================================================
# REGISTER
# =====================================================

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
        DO UPDATE SET username = EXCLUDED.username;
    """, (uuid_val, username))

    conn.commit()
    cur.close()
    conn.close()

    pretty = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🧠 SOCIAL MISSION HUD\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 Registered: {username}\n"
        "🎯 Ready for missions.\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({"pretty_text": pretty}, ensure_ascii=False),
        mimetype="application/json"
    )


# =====================================================
# START MISSION
# =====================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():

    data = request.json
    uuid_val = data["uuid"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, difficulty, description,
               tier1_required, tier2_required, tier3_required
        FROM missions
        ORDER BY RANDOM()
        LIMIT 1;
    """)

    mission = cur.fetchone()

    if not mission:
        return jsonify({"error": "No missions available"}), 400

    session_id = str(uuid.uuid4())

    cur.execute("""
        INSERT INTO mission_sessions
        (session_id, player_uuid, mission_id, expires_at)
        VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour');
    """, (session_id, uuid_val, mission[0]))

    conn.commit()
    cur.close()
    conn.close()

    pretty = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 NEW MISSION\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧩 {mission[1]} ({mission[2]})\n\n"
        f"📜 {mission[3]}\n\n"
        f"🥉 Tier 1: {mission[4]} replies\n"
        f"🥈 Tier 2: {mission[5]} replies\n"
        f"🥇 Tier 3: {mission[6]} replies\n\n"
        "⏳ Duration: 1 hour\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({
            "session_id": session_id,
            "pretty_text": pretty
        }, ensure_ascii=False),
        mimetype="application/json"
    )


# =====================================================
# COMPLETE MISSION
# =====================================================

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
        return jsonify({"error": "Invalid session"}), 400

    mission_id, tier, player_uuid = result

    cur.execute("""
        SELECT base_points, tier1_points, tier2_points, tier3_points
        FROM missions WHERE id = %s;
    """, (mission_id,))

    base, t1, t2, t3 = cur.fetchone()

    total = base
    if tier >= 1: total += t1
    if tier >= 2: total += t2
    if tier >= 3: total += t3

    cur.execute("""
        UPDATE players
        SET total_points = total_points + %s
        WHERE uuid = %s;
    """, (total, player_uuid))

    cur.execute("""
        UPDATE mission_sessions
        SET completed = TRUE
        WHERE session_id = %s;
    """, (session_id,))

    conn.commit()
    cur.close()
    conn.close()

    pretty = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 MISSION COMPLETE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🥇 Final Tier: {tier}\n"
        f"💎 Points Earned: {total}\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    return Response(
        json.dumps({"pretty_text": pretty}, ensure_ascii=False),
        mimetype="application/json"
    )


# =====================================================
# LEADERBOARD (SL SAFE)
# =====================================================

@app.route("/leaderboard/sl")
def leaderboard_sl():

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

    pretty = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 SOCIAL MISSION RANKING\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    medals = ["🥇","🥈","🥉"]

    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else "🔹"
        pretty += f"{medal} {r[0]} — {r[1]} pts\n"

    pretty += "━━━━━━━━━━━━━━━━━━"

    return Response(
        json.dumps({"pretty_text": pretty}, ensure_ascii=False),
        mimetype="application/json"
    )


# =====================================================
# RENDER SAFE
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
