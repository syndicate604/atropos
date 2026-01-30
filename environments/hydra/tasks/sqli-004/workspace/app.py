"""Vulnerable Flask app with SQL injection in LIMIT."""
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)

def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL)")
    for i in range(10):
        conn.execute(f"INSERT INTO posts (title, content) VALUES ('Post {i}', 'Content {i}')")
    conn.commit()

@app.route("/posts")
def get_posts():
    """VULNERABLE: SQL injection in LIMIT clause."""
    limit = request.args.get("limit", "5")
    conn = get_db()
    init_db(conn)
    sql = f"SELECT * FROM posts LIMIT {limit}"
    cursor = conn.execute(sql)
    return jsonify({"posts": [dict(row) for row in cursor.fetchall()]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
