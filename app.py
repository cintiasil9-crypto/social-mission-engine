import os
import psycopg2
from flask import Flask, request, jsonify

# =================================================
# APP SETUP
# =================================================

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    return psycopg2.connect(DATABASE_URL)


# =================================================
# ROOT
# =================================================

@app.route("/")
def home():
    return "Social Mission Engine Running"


# =================================================
# INIT DATABASE
# =================================================

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
        tier1_count INTEGER DEFAULT 0,
        tier2_count INTEGER DEFAULT 0,
        tier3_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # POINTS LOG
    cur.execute("""
    CREATE TABLE IF NOT EXISTS points_log (
        id SERIAL PRIMARY KEY,
        player_uuid TEXT NOT NULL,
        points INTEGER NOT NULL,
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # MISSIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        difficulty INTEGER NOT NULL,
        points INTEGER NOT NULL
    );
    """)

    # ACTIVE MISSIONS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS active_missions (
        id SERIAL PRIMARY KEY,
        player_uuid TEXT NOT NULL,
        mission_id INTEGER NOT NULL,
        progress INTEGER DEFAULT 0,
        required INTEGER DEFAULT 1,
        expires_at TIMESTAMP,
        completed BOOLEAN DEFAULT FALSE
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Database initialized."


# =================================================
# REGISTER PLAYER
# =================================================

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    uuid = data["uuid"]
    username = data["username"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO players (uuid, username)
        VALUES (%s, %s)
        ON CONFLICT (uuid)
        DO UPDATE SET username = EXCLUDED.username
        RETURNING id, influence_rating, total_points;
    """, (uuid, username))

    result = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "id": result[0],
        "influence_rating": result[1],
        "total_points": result[2]
    })


# =================================================
# ADD POINTS
# =================================================

@app.route("/add-points", methods=["POST"])
def add_points():
    data = request.json
    uuid = data["uuid"]
    points = data["points"]
    reason = data.get("reason", "mission")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE players
        SET total_points = total_points + %s
        WHERE uuid = %s
        RETURNING total_points;
    """, (points, uuid))

    result = cur.fetchone()

    if not result:
        cur.close()
        conn.close()
        return jsonify({"error": "Player not found"}), 404

    new_total = result[0]

    cur.execute("""
        INSERT INTO points_log (player_uuid, points, reason)
        VALUES (%s, %s, %s);
    """, (uuid, points, reason))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "new_total": new_total
    })


# =================================================
# LEADERBOARD
# =================================================

@app.route("/leaderboard")
def leaderboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points, influence_rating
        FROM players
        ORDER BY total_points DESC
        LIMIT 10;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    results = []
    for r in rows:
        results.append({
            "username": r[0],
            "points": r[1],
            "rating": r[2]
        })

    return jsonify(results)


# =================================================
# ASSIGN RANDOM MISSION
# =================================================

@app.route("/assign-mission", methods=["POST"])
def assign_mission():
    data = request.json
    uuid = data["uuid"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, points FROM missions ORDER BY RANDOM() LIMIT 1;")
    mission = cur.fetchone()

    if not mission:
        cur.close()
        conn.close()
        return jsonify({"error": "No missions available"}), 400

    mission_id = mission[0]

    cur.execute("""
        INSERT INTO active_missions (player_uuid, mission_id, expires_at)
        VALUES (%s, %s, NOW() + INTERVAL '1 hour')
        RETURNING id;
    """, (uuid, mission_id))

    active_id = cur.fetchone()[0]

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "active_mission_id": active_id,
        "mission_id": mission_id
    })


# =================================================
# RUN APP (Render Compatible)
# =================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
