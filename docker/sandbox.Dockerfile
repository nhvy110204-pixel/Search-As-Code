FROM python:3.12-slim

# Create a non-root group and user
RUN groupadd -r sandbox && useradd -r -g sandbox -m sandbox

# Create workspace and app directories
RUN mkdir -p /app /workspace && \
    chown -R sandbox:sandbox /app /workspace

# Copy requirements and install dependencies
COPY requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt && \
    pip uninstall -y pip && \
    rm -rf /root/.cache /tmp/requirements-sandbox.txt

# Switch to sandbox user
USER sandbox

# Set working directory
WORKDIR /app
