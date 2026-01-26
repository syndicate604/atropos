# harness/Dockerfile
FROM python:3.11-slim

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install semgrep (pinned version)
RUN pip install --no-cache-dir semgrep==1.56.0

# Install Python test deps (pinned)
COPY requirements.txt /harness/requirements.txt
RUN pip install --no-cache-dir -r /harness/requirements.txt

# Copy semgrep rules
COPY semgrep-rules/ /harness/semgrep-rules/

# Create directories that tools need to write to
# (even in read-only mode, /tmp is writable via tmpfs)
RUN mkdir -p /tmp/pycache /tmp/pytest /tmp/semgrep-cache

# Environment to prevent write attempts to read-only mounts
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPYCACHEPREFIX=/tmp/pycache
ENV HOME=/tmp
ENV SEMGREP_CACHE_DIR=/tmp/semgrep-cache

# Working directory
WORKDIR /workspace

# Default command
CMD ["python", "--version"]
