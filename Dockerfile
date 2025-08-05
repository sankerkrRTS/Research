# Use official Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source code
COPY . .

# Tell Azure and Docker what internal port this app listens on
EXPOSE 8000

# Run the Gradio app
CMD ["python", "app.py"]
