"""Vulnerable Flask app with path traversal."""
from flask import Flask, request, send_file, jsonify
import os

app = Flask(__name__)

@app.route("/download")
def download_file():
    """VULNERABLE: Path traversal in filename parameter."""
    filename = request.args.get("file", "")
    filepath = os.path.join("/workspace/files", filename)
    try:
        return send_file(filepath)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
