"""Vulnerable Flask app with SQL injection in UPDATE."""
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)

def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn

def init_db(conn):
    conn.execute("CREATE TABLE profiles (id INTEGER PRIMARY KEY, username TEXT, email TEXT)")
    conn.execute("INSERT INTO profiles (username, email) VALUES ('alice', 'alice@example.com')")
    conn.commit()

@app.route("/profile", methods=["POST"])
def update_profile():
    """VULNERABLE: SQL injection in UPDATE SET clause."""
    username = request.json.get("username", "")
    email = request.json.get("email", "")
    conn = get_db()
    init_db(conn)
    sql = f"UPDATE profiles SET email = '{email}' WHERE username = '{username}'"
    conn.execute(sql)
    conn.commit()
    return jsonify({"status": "updated"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
