import os
import sqlite3
import uuid
from flask import Flask, request, jsonify, Response

app = Flask(__name__)
DB_PATH = "mission.db"


# =====================================================
# DATABASE INIT
# =====================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT UNIQUE,
        username TEXT,
        total_points INTEGER DEFAULT 0,
        influence_rating INTEGER DEFAULT 1000
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        difficulty TEXT,
        base_points INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        player_uuid TEXT,
        mission_id INTEGER,
        completed INTEGER DEFAULT 0
    )
    """)

    # Seed missions if empty
    cur.execute("SELECT COUNT(*) FROM missions")
    if cur.fetchone()[0] == 0:
        cur.execute("""
        INSERT INTO missions (name, difficulty, base_points) VALUES
        ('Spotlight Puller','easy',25),
        ('Conversation Driver','medium',50),
        ('Social Dominator','hard',100)
        """)

    conn.commit()
    conn.close()

init_db()


# =====================================================
# ROOT
# =====================================================

@app.route("/")
def home():
    return "Social Mission Engine Running"


# =====================================================
# REGISTER
# =====================================================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True) or {}
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
        UPDATE players SET username=? WHERE uuid=?
    """, (username, uuid_val))

    cur.execute("""
        SELECT influence_rating, total_points
        FROM players WHERE uuid=?
    """, (uuid_val,))

    row = cur.fetchone()
    conn.commit()
    conn.close()

    return jsonify({
        "rating": row[0],
        "points": row[1]
    })


# =====================================================
# START MISSION
# =====================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():

    data = request.get_json(silent=True) or {}
    uuid_val = data.get("uuid")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, base_points
        FROM missions
        ORDER BY RANDOM()
        LIMIT 1
    """)

    mission = cur.fetchone()

    if not mission:
        return jsonify({"error": "No missions found"}), 400

    session_id = str(uuid.uuid4())

    cur.execute("""
        INSERT INTO sessions (session_id, player_uuid, mission_id)
        VALUES (?, ?, ?)
    """, (session_id, uuid_val, mission[0]))

    conn.commit()
    conn.close()

    return jsonify({
        "session_id": session_id,
        "mission_name": mission[1],
        "tier": 0
    })


# =====================================================
# COMPLETE MISSION
# =====================================================

@app.route("/complete-mission", methods=["POST"])
def complete_mission():

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT mission_id, player_uuid
        FROM sessions
        WHERE session_id=? AND completed=0
    """, (session_id,))

    row = cur.fetchone()

    if not row:
        return jsonify({"error": "Invalid session"}), 400

    mission_id, player_uuid = row

    cur.execute("""
        SELECT base_points FROM missions WHERE id=?
    """, (mission_id,))

    points = cur.fetchone()[0]

    cur.execute("""
        UPDATE players
        SET total_points = total_points + ?
        WHERE uuid=?
    """, (points, player_uuid))

    cur.execute("""
        UPDATE sessions
        SET completed=1
        WHERE session_id=?
    """, (session_id,))

    conn.commit()
    conn.close()

    return jsonify({
        "final_tier": 1,
        "points_awarded": points
    })


# =====================================================
# LEADERBOARD (SL SAFE)
# =====================================================

@app.route("/leaderboard/sl")
def leaderboard_sl():

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    text = "━━━━━━━━━━━━━━━━━━━━\n"
    text += "🏆 SOCIAL MISSION RANKINGS\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    medals = ["🥇","🥈","🥉"]

    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else "🔹"
        text += f"{medal} {r[0]} — {r[1]} pts\n"

    text += "\nKeep climbing.\n"
    text += "━━━━━━━━━━━━━━━━━━━━"

    return Response(
        '{"pretty_text": "' + text.replace('"','\\"') + '"}',
        mimetype="application/json; charset=utf-8"
    )


# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
