"""Vulnerable Flask app with stored XSS."""
from flask import Flask, request, jsonify
import sqlite3

app = Flask(__name__)
comments = []

@app.route("/comment", methods=["POST"])
def add_comment():
    """VULNERABLE: Stored XSS - no sanitization."""
    comment = request.json.get("comment", "")
    comments.append(comment)
    return jsonify({"status": "added"})

@app.route("/comments")
def view_comments():
    """Display comments without escaping."""
    html = "<html><body><h1>Comments</h1>"
    for c in comments:
        html += f"<p>{c}</p>"
    html += "</body></html>"
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
