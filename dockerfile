# Use Python 3.9 slim image to match your temp env
FROM python:3.9-slim

# Set working directory inside the container
WORKDIR /app

# Copy your project code into the container
COPY . /app

# Install dependencies from requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Command to run your bot
CMD ["python", "-m", "tests.main"]
