from flask import Flask, jsonify, request, Response
import sqlite3
import uuid
import time
import os

app = Flask(__name__)

DB_PATH = "mission_engine.db"


# ======================================================
# DATABASE
# ======================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/init-db")
def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        uuid TEXT PRIMARY KEY,
        username TEXT,
        total_points INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        description TEXT,
        objective TEXT,
        tier1 INTEGER,
        tier2 INTEGER,
        tier3 INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        player_uuid TEXT,
        mission_id INTEGER,
        progress INTEGER DEFAULT 0,
        tier INTEGER DEFAULT 0,
        started_at INTEGER
    )
    """)

    conn.commit()
    conn.close()

    return "DB Ready"


# ======================================================
# SEED MISSIONS
# ======================================================

@app.route("/seed-missions")
def seed():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM missions")

    missions = [
        ("Spotlight Puller",
         "Pull attention and spark replies.",
         "Get multiple people talking.",
         10, 15, 25),

        ("Conversation Driver",
         "Drive group discussion forward.",
         "Keep 3+ avatars engaged.",
         20, 30, 50),

        ("Social Dominator",
         "Control the social flow.",
         "Lead the room confidently.",
         40, 60, 100),
    ]

    cur.executemany("""
        INSERT INTO missions
        (name, description, objective, tier1, tier2, tier3)
        VALUES (?, ?, ?, ?, ?, ?)
    """, missions)

    conn.commit()
    conn.close()

    return "Seeded"


# ======================================================
# REGISTER
# ======================================================

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    uuid_val = data["uuid"]
    username = data["username"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO players (uuid, username)
        VALUES (?, ?)
    """, (uuid_val, username))

    conn.commit()
    conn.close()

    return jsonify({
        "pretty_text":
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ REGISTERED\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 {username}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    })


# ======================================================
# START MISSION
# ======================================================

@app.route("/start-mission", methods=["POST"])
def start_mission():
    data = request.get_json()
    player_uuid = data["uuid"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM missions ORDER BY RANDOM() LIMIT 1")
    mission = cur.fetchone()

    session_id = str(uuid.uuid4())

    cur.execute("""
        INSERT INTO sessions
        (session_id, player_uuid, mission_id, started_at)
        VALUES (?, ?, ?, ?)
    """, (session_id, player_uuid, mission["id"], int(time.time())))

    conn.commit()
    conn.close()

    pretty = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 NEW MISSION\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 {mission['name']}\n\n"
        f"{mission['description']}\n\n"
        f"🥉 {mission['tier1']} pts\n"
        f"🥈 {mission['tier2']} pts\n"
        f"🥇 {mission['tier3']} pts\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )

    return jsonify({
        "session_id": session_id,
        "pretty_text": pretty
    })


# ======================================================
# COMPLETE TIER
# ======================================================

@app.route("/complete-tier", methods=["POST"])
def complete_tier():
    data = request.get_json()
    session_id = data["session_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,))
    session = cur.fetchone()

    new_tier = session["tier"] + 1

    cur.execute("""
        UPDATE sessions
        SET tier=?
        WHERE session_id=?
    """, (new_tier, session_id))

    conn.commit()
    conn.close()

    return jsonify({
        "pretty_text":
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⬆ Tier Advanced → {new_tier}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    })


# ======================================================
# COMPLETE MISSION
# ======================================================

@app.route("/complete-mission", methods=["POST"])
def complete_mission():
    data = request.get_json()
    session_id = data["session_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,))
    session = cur.fetchone()

    cur.execute("SELECT * FROM missions WHERE id=?", (session["mission_id"],))
    mission = cur.fetchone()

    tier = session["tier"]

    points = 0
    if tier == 1:
        points = mission["tier1"]
    elif tier == 2:
        points = mission["tier2"]
    elif tier >= 3:
        points = mission["tier3"]

    cur.execute("""
        UPDATE players
        SET total_points = total_points + ?
        WHERE uuid=?
    """, (points, session["player_uuid"]))

    cur.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))

    conn.commit()
    conn.close()

    return jsonify({
        "pretty_text":
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 MISSION COMPLETE\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Points Earned: {points}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    })


# ======================================================
# LEADERBOARD SL
# ======================================================

@app.route("/leaderboard/sl")
def leaderboard_sl():
    conn = get_db()
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
    text += "🏆 MISSION LEADERBOARD\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n\n"

    medals = ["🥇","🥈","🥉"]

    for i, r in enumerate(rows):
        medal = medals[i] if i < 3 else " "
        text += f"{medal} {r['username']} — {r['total_points']} pts\n"

    text += "━━━━━━━━━━━━━━━━━━━━"

    return jsonify({"pretty_text": text})


# ======================================================
# LEADERBOARD HTML
# ======================================================

@app.route("/leaderboard/html")
def leaderboard_html():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
        LIMIT 10
    """)

    rows = cur.fetchall()
    conn.close()

    html = """
    <html>
    <head>
    <meta http-equiv="refresh" content="60">
    <style>
    body { font-family: Arial; background:#111; color:white; text-align:center; }
    h1 { margin-top:40px; }
    table { margin:auto; margin-top:30px; width:50%; border-collapse:collapse; }
    th, td { padding:12px; border-bottom:1px solid #333; }
    th { background:#222; }
    </style>
    </head>
    <body>
    <h1>🏆 Mission Leaderboard</h1>
    <table>
    <tr><th>Rank</th><th>Avatar</th><th>Points</th></tr>
    """

    for i, r in enumerate(rows):
        html += f"<tr><td>{i+1}</td><td>{r['username']}</td><td>{r['total_points']}</td></tr>"

    html += "</table></body></html>"

    return html


@app.route("/")
def ok():
    return "Mission Engine Running"


# ======================================================
# RENDER SAFE
# ======================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
