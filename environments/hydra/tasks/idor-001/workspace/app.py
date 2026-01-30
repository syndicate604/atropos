"""Vulnerable Flask app with IDOR."""
from flask import Flask, request, jsonify, session
import sqlite3

app = Flask(__name__)
app.secret_key = "insecure"

def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT, is_admin INTEGER)")
    conn.execute("INSERT INTO users VALUES (1, 'alice', 'alice@example.com', 0)")
    conn.execute("INSERT INTO users VALUES (2, 'bob', 'bob@example.com', 0)")
    conn.execute("INSERT INTO users VALUES (3, 'admin', 'admin@example.com', 1)")
    conn.commit()

@app.route("/profile")
def get_profile():
    """VULNERABLE: IDOR - no authorization check."""
    user_id = request.args.get("id", "1")
    conn = get_db()
    init_db(conn)
    cursor = conn.execute(f"SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    return jsonify(dict(user) if user else {})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
