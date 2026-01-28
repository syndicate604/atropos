"""Vulnerable Flask app with SQL injection in DELETE."""
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)

def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, user_id INTEGER, token TEXT)")
    conn.execute("INSERT INTO sessions (user_id, token) VALUES (1, 'abc123')")
    conn.execute("INSERT INTO sessions (user_id, token) VALUES (2, 'def456')")
    conn.commit()

@app.route("/logout", methods=["POST"])
def logout():
    """VULNERABLE: SQL injection in DELETE WHERE clause."""
    token = request.json.get("token", "")
    conn = get_db()
    init_db(conn)
    # VULNERABLE: String concatenation in DELETE
    sql = f"DELETE FROM sessions WHERE token = '{token}'"
    conn.execute(sql)
    conn.commit()
    return jsonify({"status": "logged out"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
