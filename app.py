import os
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)


# ===============================
# BASIC STATUS
# ===============================

@app.route("/")
def home():
    return "Social Mission Engine Running"


# ===============================
# INIT DB (run once)
# ===============================

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
        tier3_count INTEGER DEFAULT 0,
        influence_rating INTEGER DEFAULT 1000,
        streak_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()

    return "Database initialized."


# ===============================
# CREATE OR GET PLAYER
# ===============================

@app.route("/player", methods=["POST"])
def create_or_get_player():
    data = request.json
    uuid = data.get("uuid")
    username = data.get("username")

    if not uuid:
        return jsonify({"error": "UUID required"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO players (uuid, username)
        VALUES (%s, %s)
        ON CONFLICT (uuid)
        DO UPDATE SET username = EXCLUDED.username
        RETURNING id, uuid, username, total_points, influence_rating;
    """, (uuid, username))

    player = cur.fetchone()
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "id": player[0],
        "uuid": player[1],
        "username": player[2],
        "total_points": player[3],
        "influence_rating": player[4]
    })


# ===============================
# ADD POINTS
# ===============================

@app.route("/add-points", methods=["POST"])
def add_points():
    data = request.json
    uuid = data.get("uuid")
    points = data.get("points", 0)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE players
        SET total_points = total_points + %s
        WHERE uuid = %s
        RETURNING total_points;
    """, (points, uuid))

    result = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    if not result:
        return jsonify({"error": "Player not found"}), 404

    return jsonify({"new_total": result[0]})


# ===============================
# LEADERBOARD
# ===============================

@app.route("/leaderboard")
def leaderboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT username, total_points
        FROM players
        ORDER BY total_points DESC
        LIMIT 20;
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    leaderboard = [
        {"username": r[0], "points": r[1]}
        for r in rows
    ]

    return jsonify(leaderboard)


# ===============================
# RUN
# ===============================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
