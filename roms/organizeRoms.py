import os
import sys
import shutil

ROM_TYPES = {
    'nes': ['nes', 'NES'],
    'snes': ['sfc', 'smc'],
    'n64': ['n64', 'z64'],
    'gba': ['gba'],
    'genesis': ['gen', 'bin', 'md'],
    'dreamcast': ['gdi', 'cdi'],
    'gamecube': ['iso', 'gcm'],
    'wii': ['iso', 'wii'],
    'psx': ['bin', 'iso', 'cue', 'img'],
    'ps2': ['iso', 'bin', 'cue', 'img'],
    'ps3': ['iso', 'bin', 'cue', 'img'],
    # Add more systems and their file extensions as needed
}

def organize_roms(root_directory):
    print(f"\nStarting ROM organization in: {root_directory}")
    total_moved = 0
    
    for system, extensions in ROM_TYPES.items():
        print(f"\nProcessing {system.upper()} ROMs (looking for extensions: {', '.join(extensions)})")
        system_dir = os.path.join(root_directory, system)
        os.makedirs(system_dir, exist_ok=True)
        system_count = 0
        
        for ext in extensions:
            for root, _, files in os.walk(root_directory):
                for file in files:
                    if file.lower().endswith(f'.{ext.lower()}'):
                        src = os.path.join(root, file)
                        dst = os.path.join(system_dir, file)
                        
                        try:
                            shutil.move(src, dst)
                            system_count += 1
                            total_moved += 1
                            print(f"✓ Moved: {file}")
                            print(f"  From: {root}")
                            print(f"  To:   {system_dir}")
                        except Exception as e:
                            print(f"✗ Error moving {file}: {str(e)}")
        
        if system_count == 0:
            print(f"No {system.upper()} ROMs found")
        else:
            print(f"\nTotal {system.upper()} ROMs moved: {system_count}")
    
    print(f"\nOrganization complete! Total files moved: {total_moved}")

if len(sys.argv) != 2:
    print("Usage: python organizeRoms.py <root_directory_path>")
    sys.exit(1)

root_directory = sys.argv[1]
if not os.path.isdir(root_directory):
    print("Invalid directory path. Please try again.")
    sys.exit(1)

organize_roms(root_directory)
