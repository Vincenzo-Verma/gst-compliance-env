FROM --platform=linux/amd64 python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Generate synthetic invoice data at build time
RUN python -c "\
import sys; \
sys.path.insert(0, '/app'); \
from env.data.generator import generate_all_invoice_sets; \
import json, pathlib; \
data = generate_all_invoice_sets(); \
p = pathlib.Path('env/data/invoices_seed.json'); \
p.parent.mkdir(parents=True, exist_ok=True); \
open(p, 'w').write(json.dumps(data, indent=2)); \
print('Invoice data generated successfully') \
"

# Expose HF Spaces port
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Start FastAPI server
CMD ["uvicorn", "env.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
