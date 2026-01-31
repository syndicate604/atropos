# tasks/sqli-003/workspace/app.py
"""Vulnerable Flask app with SQL injection in ORDER BY."""

from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)


def get_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL NOT NULL
        )
    """)
    conn.execute("INSERT INTO products (name, price) VALUES ('Widget', 10.99)")
    conn.execute("INSERT INTO products (name, price) VALUES ('Gadget', 25.50)")
    conn.execute("INSERT INTO products (name, price) VALUES ('Tool', 15.00)")
    conn.commit()


@app.route("/products")
def list_products():
    """Get products sorted by column name."""
    sort = request.args.get("sort", "id")
    
    conn = get_db()
    init_db(conn)

    sql = f"SELECT * FROM products ORDER BY {sort}"
    cursor = conn.execute(sql)

    results = [dict(row) for row in cursor.fetchall()]
    return jsonify({"products": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
