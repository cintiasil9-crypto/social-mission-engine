import os
import sqlite3
import uuid
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

DB_PATH = "mission.db"


# =====================================================
# DATABASE INIT (AUTO RUNS ON STARTUP)
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
        influence_rating INTEGER DEFAULT 1000,
        streak_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_sessions (
        id TEXT PRIMARY KEY,
        player_uuid TEXT,
        mission_name TEXT,
        completed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        difficulty TEXT,
        description TEXT,
        objective TEXT,
        tier1_required INTEGER,
        tier2_required INTEGER,
        tier3_required INTEGER,
        base_points INTEGER,
        tier1_points INTEGER,
        tier2_points INTEGER,
        tier3_points INTEGER
    )
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
        UPDATE players SET username = ?
        WHERE uuid = ?
    """, (username, uuid_val))

    cur.execute("""
        SELECT influence_rating, total_points
        FROM players WHERE uuid = ?
    """, (uuid_val,))

    row = cur.fetchone()
    conn.commit()
    conn.close()

    return jsonify({
        "rating": row[0],
        "points": row[1]
    })


# =====================================================
# LEADERBOARD (SL JSON)
# =====================================================

@app.route("/leaderboard")
def leaderboard():

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

    return jsonify([
        {"username": r[0], "points": r[1]}
        for r in rows
    ])


# =====================================================
# PRETTY LEADERBOARD FOR SL (EMOJI SAFE)
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

    medals = ["🥇", "🥈", "🥉"]

    i = 0
    for r in rows:
        medal = medals[i] if i < 3 else "🔹"
        text += f"{medal} {r[0]} — {r[1]} pts\n"
        i += 1

    text += "\nKeep climbing.\n"
    text += "━━━━━━━━━━━━━━━━━━━━"

    return Response(
        jsonify({"pretty_text": text}).get_data(as_text=True),
        mimetype="application/json; charset=utf-8"
    )


# =====================================================
# HTML LEADERBOARD (BROWSER)
# =====================================================

@app.route("/leaderboard/html")
def leaderboard_html():

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
    """)

    rows = cur.fetchall()
    conn.close()

    html = """
    <html>
    <head>
    <style>
    body { font-family: Arial; background:#111; color:white; padding:40px; }
    table { width:600px; border-collapse:collapse; }
    th,td { padding:12px; border-bottom:1px solid #333; }
    th { background:#222; }
    tr:hover { background:#1e1e1e; }
    </style>
    </head>
    <body>
    <h1>🏆 Social Mission Leaderboard</h1>
    <table>
    <tr><th>Rank</th><th>Name</th><th>Points</th></tr>
    """

    rank = 1
    for r in rows:
        html += f"<tr><td>{rank}</td><td>{r[0]}</td><td>{r[1]}</td></tr>"
        rank += 1

    html += "</table></body></html>"

    return html

@app.route("/start-mission", methods=["POST"])
def start_mission():

    data = request.get_json(silent=True) or {}
    uuid_val = data.get("uuid")

    if not uuid_val:
        return jsonify({"error": "Missing UUID"}), 400

    session_id = str(uuid.uuid4())

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO mission_sessions (id, player_uuid, mission_name)
        VALUES (?, ?, ?)
    """, (session_id, uuid_val, "Spotlight Puller"))

    conn.commit()
    conn.close()

    return jsonify({
        "session_id": session_id,
        "pretty_text": "🎯 Mission Started: Spotlight Puller\nGet multiple people replying in chat."
    })

@app.route("/complete-mission", methods=["POST"])
def complete_mission():

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT player_uuid FROM mission_sessions
        WHERE id = ? AND completed = 0
    """, (session_id,))

    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Invalid or completed session"}), 400

    player_uuid = row[0]

    # Mark completed
    cur.execute("""
        UPDATE mission_sessions
        SET completed = 1
        WHERE id = ?
    """, (session_id,))

    # Award points
    cur.execute("""
        UPDATE players
        SET total_points = total_points + 100
        WHERE uuid = ?
    """, (player_uuid,))

    conn.commit()
    conn.close()

    return jsonify({
        "pretty_text": "🏆 Mission Complete!\n+100 Points Awarded."
    })

# =====================================================
# START SERVER
# =====================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
