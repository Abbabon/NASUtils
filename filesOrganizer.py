import os
import shutil
from pathlib import Path
from datetime import datetime
import sys
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("organizer.log")])

def organize_files_by_date(input_path, output_parent_path):
    input_path = Path(input_path)
    output_parent_path = Path(output_parent_path)
    
    if not input_path.exists():
        logging.error(f"Input path {input_path} does not exist.")
        return
    
    if not output_parent_path.exists():
        logging.error(f"Output parent path {output_parent_path} does not exist.")
        return
    
    for file in input_path.glob('*'):
        if file.is_file():
            # Get the file creation time
            created_time = datetime.fromtimestamp(file.stat().st_ctime)
            year = created_time.strftime('%Y')
            month = created_time.strftime('%m')
            
            # Create the destination directory path
            dest_dir = output_parent_path / year / month
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Move the file to the new directory
            dest_file = dest_dir / file.name
            shutil.move(str(file), dest_file)
            logging.info(f"Moved {file} to {dest_file}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        logging.error("Usage: python script.py <input_directory> <output_parent_directory>")
        sys.exit(1)
    
    input_directory = sys.argv[1]
    output_parent_directory = sys.argv[2]

    while True:
        organize_files_by_date(input_directory, output_parent_directory)
        logging.info("Waiting for 1 minute...")
        time.sleep(60)