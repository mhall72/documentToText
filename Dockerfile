# Use the official Python image as the base
FROM python:3.9-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    libmupdf-dev \
    tesseract-ocr \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set the working directory
WORKDIR /app

# Copy the application code
COPY . .

# Expose port 5000
EXPOSE 5000

# Run the application
CMD ["python", "main.py"]
