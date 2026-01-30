# tasks/sqli-002/workspace/app.py
"""Vulnerable Flask app with SQL injection in user lookup."""

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
        "INSERT INTO users (username, email) VALUES ('charlie', 'charlie@example.com')"
    )
    conn.commit()


@app.route("/user")
def get_user():
    """Get user by ID."""
    user_id = request.args.get("id", "")

    if not user_id:
        return jsonify({"users": []})

    conn = get_db()
    init_db(conn)

    sql = f"SELECT * FROM users WHERE id = {user_id}"
    cursor = conn.execute(sql)

    results = [dict(row) for row in cursor.fetchall()]
    return jsonify({"users": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
