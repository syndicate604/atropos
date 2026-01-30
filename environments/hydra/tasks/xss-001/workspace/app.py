"""Vulnerable Flask app with reflected XSS."""
from flask import Flask, request

app = Flask(__name__)

@app.route("/search")
def search():
    """Search and display results."""
    query = request.args.get("q", "")
    html = f"""
    <html>
    <head><title>Search Results</title></head>
    <body>
        <h1>Search results for: {query}</h1>
        <p>No results found.</p>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
