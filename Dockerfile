FROM python:3.12-slim-trixie

WORKDIR /app

# Streams logs immediately instead of buffering — matters here since Cloud Run's real-time log
# visibility is how you'd actually watch the pipeline run.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Matches Cloud Run's own default injected PORT — set explicitly here too so a plain
# `docker run -p 8080:8080` works locally with no extra flags, same as the real deployment.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
