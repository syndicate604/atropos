"""Vulnerable Flask app with command injection."""
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route("/ping")
def ping():
    """VULNERABLE: Command injection in host parameter."""
    host = request.args.get("host", "localhost")
    # VULNERABLE: Shell=True with user input
    result = subprocess.run(
        f"ping -c 1 {host}",
        shell=True,
        capture_output=True,
        text=True
    )
    return jsonify({"output": result.stdout})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
