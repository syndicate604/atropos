# tasks/sqli-001/workspace/app.py
"""Vulnerable Flask app with SQL injection."""

from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO users (username, email) VALUES ('alice', 'alice@example.com')"
    )
    conn.execute(
        "INSERT INTO users (username, email) VALUES ('bob', 'bob@example.com')"
    )
    conn.execute(
        "INSERT INTO users (username, email) VALUES ('admin', 'admin@secret.com')"
    )
    conn.commit()


@app.route("/search")
def search_users():
    """Search users by username."""
    query = request.args.get("q", "")

    conn = get_db()
    init_db(conn)

    sql = f"SELECT * FROM users WHERE username LIKE '%{query}%'"
    cursor = conn.execute(sql)

    results = [dict(row) for row in cursor.fetchall()]
    return jsonify({"results": results, "count": len(results)})


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
