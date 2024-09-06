import os
import sys
import shutil

ROM_TYPES = {
    'nes': ['nes', 'NES'],
    'snes': ['sfc', 'smc'],
    'n64': ['n64', 'z64'],
    'gba': ['gba'],
    'genesis': ['gen', 'bin', 'md'],
    # Add more systems and their file extensions as needed
}

def organize_roms(root_directory):
    for system, extensions in ROM_TYPES.items():
        system_dir = os.path.join(root_directory, system)
        os.makedirs(system_dir, exist_ok=True)
        
        for ext in extensions:
            for root, _, files in os.walk(root_directory):
                for file in files:
                    if file.lower().endswith(f'.{ext.lower()}'):
                        src = os.path.join(root, file)
                        dst = os.path.join(system_dir, file)
                        shutil.move(src, dst)
                        print(f"Moved {file} to {system} folder")

if len(sys.argv) != 2:
    print("Usage: python organizeRoms.py <root_directory_path>")
    sys.exit(1)

root_directory = sys.argv[1]
if not os.path.isdir(root_directory):
    print("Invalid directory path. Please try again.")
    sys.exit(1)

organize_roms(root_directory)
