import os
import uuid
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

COOLDOWN_SECONDS = 1800      # 30 minutes
MISSION_DURATION = 3600      # 1 hour
ANTI_SPAM_SECONDS = 10       # Same avatar can't count twice within 10 sec


# =========================================================
# DB CONNECTION
# =========================================================

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

    # MISSIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        description TEXT NOT NULL,
        objective TEXT NOT NULL,
        tier1_required INTEGER NOT NULL,
        tier2_required INTEGER NOT NULL,
        tier3_required INTEGER NOT NULL,
        base_points INTEGER NOT NULL,
        tier1_points INTEGER NOT NULL,
        tier2_points INTEGER NOT NULL,
        tier3_points INTEGER NOT NULL
    );
    """)

    # ACTIVE SESSIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_sessions (
        id SERIAL PRIMARY KEY,
        session_id TEXT UNIQUE NOT NULL,
        player_uuid TEXT REFERENCES players(uuid) ON DELETE CASCADE,
        mission_id INTEGER REFERENCES missions(id) ON DELETE CASCADE,
        tier INTEGER DEFAULT 0,
        progress INTEGER DEFAULT 0,
        completed BOOLEAN DEFAULT FALSE,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP
    );
    """)

    # UNIQUE REPLY TRACKING
    cur.execute("""
    CREATE TABLE IF NOT EXISTS mission_replies (
        id SERIAL PRIMARY KEY,
        session_id TEXT,
        avatar_uuid TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # MISSION LOG
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
# SEED MISSIONS
# =========================================================

@app.route("/seed-missions")
def seed_missions():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO missions (
        name, difficulty, description, objective,
        tier1_required, tier2_required, tier3_required,
        base_points, tier1_points, tier2_points, tier3_points
    )
    VALUES
    (
        'Spotlight Puller',
        'easy',
        'Pull attention and generate replies from different avatars.',
        'Get replies from different avatars.',
        1, 3, 5,
        25, 10, 15, 25
    ),
    (
        'Conversation Driver',
        'medium',
        'Start and sustain conversation.',
        'Generate sustained replies from multiple avatars.',
        3, 6, 10,
        50, 20, 30, 50
    ),
    (
        'Social Dominator',
        'hard',
        'Dominate the room socially.',
        'Generate high engagement from many avatars.',
        5, 10, 20,
        100, 40, 60, 100
    )
    ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Missions seeded."


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
# START MISSION
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
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s));", (last[0],))
        if cur.fetchone()[0] < COOLDOWN_SECONDS:
            cur.close()
            conn.close()
            return jsonify({"error": "Cooldown active"}), 400

    # Active session?
    cur.execute("""
        SELECT id FROM mission_sessions
        WHERE player_uuid = %s
        AND completed = FALSE
        AND expires_at > NOW();
    """, (uuid_val,))

    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "Active mission exists"}), 400

    # Pick random mission
    cur.execute("""
        SELECT id, name, description, objective,
               tier1_required, tier2_required, tier3_required
        FROM missions
        ORDER BY RANDOM()
        LIMIT 1;
    """)

    mission = cur.fetchone()

    if not mission:
        cur.close()
        conn.close()
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

    return jsonify({
        "session_id": session_id,
        "mission_name": mission[1],
        "description": mission[2],
        "objective": mission[3],
        "tier1_required": mission[4],
        "tier2_required": mission[5],
        "tier3_required": mission[6],
        "tier": 0,
        "progress": 0,
        "expires_in": 3600
    })


# =========================================================
# RECORD REPLY (SERVER VALIDATION)
# =========================================================

@app.route("/record-reply", methods=["POST"])
def record_reply():
    data = request.json
    session_id = data["session_id"]
    avatar_uuid = data["avatar_uuid"]

    conn = get_db()
    cur = conn.cursor()

    # Validate session
    cur.execute("""
        SELECT mission_id, tier, progress
        FROM mission_sessions
        WHERE session_id = %s
        AND completed = FALSE
        AND expires_at > NOW();
    """, (session_id,))

    result = cur.fetchone()
    if not result:
        cur.close()
        conn.close()
        return jsonify({"error": "Invalid session"}), 400

    mission_id, tier, progress = result

    # Anti spam (same avatar within 10 sec)
    cur.execute("""
        SELECT created_at FROM mission_replies
        WHERE session_id = %s
        AND avatar_uuid = %s
        ORDER BY created_at DESC
        LIMIT 1;
    """, (session_id, avatar_uuid))

    last = cur.fetchone()
    if last:
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - %s));", (last[0],))
        if cur.fetchone()[0] < ANTI_SPAM_SECONDS:
            cur.close()
            conn.close()
            return jsonify({"status": "ignored"})

    # Insert reply
    cur.execute("""
        INSERT INTO mission_replies (session_id, avatar_uuid)
        VALUES (%s, %s);
    """, (session_id, avatar_uuid))

    progress += 1

    cur.execute("""
        UPDATE mission_sessions
        SET progress = %s
        WHERE session_id = %s;
    """, (progress, session_id))

    # Check tier advancement
    cur.execute("""
        SELECT tier1_required, tier2_required, tier3_required
        FROM missions WHERE id = %s;
    """, (mission_id,))

    t1, t2, t3 = cur.fetchone()

    new_tier = tier
    if progress >= t3:
        new_tier = 3
    elif progress >= t2:
        new_tier = 2
    elif progress >= t1:
        new_tier = 1

    if new_tier != tier:
        cur.execute("""
            UPDATE mission_sessions
            SET tier = %s
            WHERE session_id = %s;
        """, (new_tier, session_id))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "progress": progress,
        "tier": new_tier
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

@app.route("/admin/missions")
def admin_missions():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            name,
            difficulty,
            base_points,
            tier1_points,
            tier2_points,
            tier3_points
        FROM missions
        ORDER BY id;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    html = """
    <html>
    <head>
        <title>Mission Admin</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f6f9;
                padding: 40px;
            }

            h1 {
                margin-bottom: 20px;
            }

            table {
                border-collapse: collapse;
                width: 100%;
                background: white;
                box-shadow: 0 4px 10px rgba(0,0,0,0.08);
            }

            th {
                background: #1f2937;
                color: white;
                padding: 12px;
                text-align: left;
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            td {
                padding: 10px;
                border-bottom: 1px solid #e5e7eb;
                font-size: 14px;
            }

            tr:nth-child(even) {
                background-color: #f9fafb;
            }

            tr:hover {
                background-color: #eef2ff;
            }

            .easy { color: #16a34a; font-weight: bold; }
            .medium { color: #d97706; font-weight: bold; }
            .hard { color: #dc2626; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>Mission Configuration Table</h1>
        <table>
            <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Difficulty</th>
                <th>Base Points</th>
                <th>Tier 1</th>
                <th>Tier 2</th>
                <th>Tier 3</th>
            </tr>
    """

    for r in rows:
        diff_class = r[2]

        html += f"""
            <tr>
                <td>{r[0]}</td>
                <td>{r[1]}</td>
                <td class="{diff_class}">{r[2]}</td>
                <td>{r[3]}</td>
                <td>{r[4]}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
            </tr>
        """

    html += """
        </table>
    </body>
    </html>
    """

    return html

@app.route("/admin/players")
def admin_players():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            username,
            uuid,
            total_points,
            influence_rating,
            streak_count,
            created_at
        FROM players
        ORDER BY total_points DESC;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    html = """
    <html>
    <head>
        <title>Player Admin</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f6f9;
                padding: 40px;
            }

            h1 {
                margin-bottom: 20px;
            }

            table {
                border-collapse: collapse;
                width: 100%;
                background: white;
                box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            }

            th {
                background: #111827;
                color: white;
                padding: 12px;
                text-align: left;
                font-size: 14px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            td {
                padding: 10px;
                border-bottom: 1px solid #e5e7eb;
                font-size: 14px;
            }

            tr:nth-child(even) {
                background-color: #f9fafb;
            }

            tr:hover {
                background-color: #eef2ff;
            }

            .points {
                font-weight: bold;
                color: #2563eb;
            }

            .rating {
                color: #7c3aed;
                font-weight: bold;
            }

            .uuid {
                font-size: 11px;
                color: #6b7280;
            }
        </style>
    </head>
    <body>
        <h1>Registered Avatars</h1>
        <table>
            <tr>
                <th>ID</th>
                <th>Username</th>
                <th>UUID</th>
                <th>Total Points</th>
                <th>Influence Rating</th>
                <th>Streak</th>
                <th>Created</th>
            </tr>
    """

    for r in rows:
        html += f"""
            <tr>
                <td>{r[0]}</td>
                <td>{r[1]}</td>
                <td class="uuid">{r[2]}</td>
                <td class="points">{r[3]}</td>
                <td class="rating">{r[4]}</td>
                <td>{r[5]}</td>
                <td>{r[6]}</td>
            </tr>
        """

    html += """
        </table>
    </body>
    </html>
    """

    return html

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
