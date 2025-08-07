# Use an official Python 3.10 base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies required by mysqlclient
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    gcc \
    python3-dev \
    libssl-dev \
    libffi-dev \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy app code
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt

# Make port available (adjust as per your app)
EXPOSE 8060

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Run app via entrypoint script
CMD ["/app/entrypoint.sh"]
