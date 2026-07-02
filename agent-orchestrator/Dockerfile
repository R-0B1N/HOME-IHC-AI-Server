FROM python:3.11-slim
WORKDIR /app

# Install git for context gathering and loop.sh
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Execute the bash loop and ensure python packages are installed
CMD ["/bin/bash", "-c", "pip install -r requirements.txt && ./loop.sh"]
