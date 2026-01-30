"""Vulnerable Flask app with command injection."""
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route("/echo")
def echo():
    """VULNERABLE: Command injection in message parameter."""
    message = request.args.get("message", "hello")
    result = subprocess.run(
        f"echo {message}",
        shell=True,
        capture_output=True,
        text=True
    )
    return jsonify({"output": result.stdout})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
