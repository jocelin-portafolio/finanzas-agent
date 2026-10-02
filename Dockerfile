FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

ENV FINANZAS_DB=/data/finanzas.db
VOLUME ["/data"]

# Por defecto: chat interactivo. Para exponer solo el servidor MCP:
#   docker run -i finanzas-agent finanzas-server
CMD ["finanzas-chat"]
