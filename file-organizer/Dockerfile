# Use the official Python base image
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the Python script to the working directory
COPY filesOrganizer.py /app/filesOrganizer.py

# If you have a requirements.txt file, uncomment the following lines
# COPY requirements.txt /app/requirements.txt
# RUN pip install --no-cache-dir -r requirements.txt

# Install any additional packages if needed
# RUN apt-get update && apt-get install -y <package-name>

# Command to run the script
CMD ["python", "filesOrganizer.py", "/input_directory", "/output_parent_directory"]