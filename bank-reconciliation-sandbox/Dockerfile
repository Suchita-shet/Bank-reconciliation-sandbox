FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
USER app

# Default: run the MCP server over stdio. No secrets are baked into the image;
# pass ANTHROPIC_API_KEY at runtime (--env-file .env) only when running evals.
CMD ["python", "-m", "bankrecon.mcp_server"]
