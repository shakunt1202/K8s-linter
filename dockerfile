# -------- Base Image --------
FROM python:3.11-slim

# -------- System deps --------
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# -------- App setup --------
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy full project
COPY . .

# -------- Environment --------
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# -------- Expose port --------
EXPOSE 8000

# -------- Run server --------
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]