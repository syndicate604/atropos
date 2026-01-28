"""Vulnerable Flask app with path traversal."""
from flask import Flask, request, send_file
import os

app = Flask(__name__)

@app.route("/download")
def download_file():
    """VULNERABLE: Path traversal in filename parameter."""
    filename = request.args.get("file", "")
    # VULNERABLE: No path validation
    filepath = os.path.join("/app/files", filename)
    return send_file(filepath)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
