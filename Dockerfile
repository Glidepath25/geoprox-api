# Dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

# System deps (optional but useful for wheels)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /code

# Install Python deps first (best layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app
COPY . .

# Make our code importable
ENV PYTHONPATH=/code

# Expose and run
ENV PORT=8000
EXPOSE 8000
CMD ["uvicorn", "geoprox.main:app", "--host", "0.0.0.0", "--port", "8000"]
