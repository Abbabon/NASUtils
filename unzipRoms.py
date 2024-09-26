import os
import zipfile
import logging

def unzip_files(directory):
    # Set up logging to file and console
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler('unzip_log.txt'),
            logging.StreamHandler()
        ]
    )

    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.lower().endswith('.zip'):
                file_path = os.path.join(root, file)
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        # Extract to the same directory as the zip file
                        zip_ref.extractall(root)
                    logging.info(f"Unzipped: {file_path}")
                    
                    # Delete the original zip file
                    os.remove(file_path)
                    logging.info(f"Deleted: {file_path}")
                except Exception as e:
                    logging.error(f"Error processing {file_path}: {str(e)}")

# Specify the directory
rom_directory = "/Volumes/Emulation/RomPacks/GB"

# Call the function to unzip files
unzip_files(rom_directory)

print("Unzipping process completed. Check unzip_log.txt for details.")
