# Build the dashboard
FROM node:22-slim AS web
WORKDIR /w
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Runtime: FastAPI serving the API, the stored replays and the built dashboard.
# Hugging Face Docker Spaces run as uid 1000 and expect port 7860.
FROM python:3.12-slim
RUN pip install --no-cache-dir uv && useradd -m -u 1000 user
USER user
ENV HOME=/home/user PYTHONPATH=src PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /home/user/app
COPY --chown=user pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY --chown=user src ./src
COPY --chown=user data ./data
COPY --chown=user --from=web /w/dist ./web/dist
# Live runs switch on only when the NEBIUS_API_KEY secret is set on the host. Replays always work.
ENV CD_ALLOW_LIVE=1
EXPOSE 7860
CMD ["uv", "run", "--no-sync", "uvicorn", "clusterdoctor.api:app", "--host", "0.0.0.0", "--port", "7860"]
