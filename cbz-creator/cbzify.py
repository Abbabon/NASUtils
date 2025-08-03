import os
import sys
import zipfile
from pathlib import Path

def create_cbz(directory_path):
    """
    Creates a CBZ file from a directory containing images.
    The CBZ will have the same name as the directory.
    """
    try:
        dir_path = Path(directory_path)
        if not dir_path.is_dir():
            print(f"Error: {directory_path} is not a directory")
            return False

        # Create CBZ filename from directory name
        cbz_filename = f"{dir_path.name}.cbz"
        cbz_path = dir_path.parent / cbz_filename

        # Common image extensions
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')

        # Get all image files in the directory
        image_files = [
            f for f in dir_path.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ]

        # Sort files to ensure consistent ordering
        image_files.sort()

        if not image_files:
            print(f"No image files found in {directory_path}")
            return False

        # Create the CBZ file
        print(f"Creating {cbz_filename}...")
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for image in image_files:
                print(f"  Adding: {image.name}")
                zf.write(image, image.name)

        print(f"Successfully created {cbz_filename}")
        return True

    except Exception as e:
        print(f"Error processing {directory_path}: {str(e)}")
        return False

def process_directory_recursively(path):
    """
    Recursively processes directories and creates CBZ files.
    Returns tuple of (success_count, error_count)
    """
    success_count = 0
    error_count = 0
    path = Path(path)

    # Process current directory
    if path.is_dir() and any(f.is_file() for f in path.iterdir()):
        print(f"\nProcessing directory: {path}")
        if create_cbz(path):
            success_count += 1
        else:
            error_count += 1

    # Recursively process subdirectories
    for item in path.iterdir():
        if item.is_dir():
            sub_success, sub_error = process_directory_recursively(item)
            success_count += sub_success
            error_count += sub_error

    return success_count, error_count

def main():
    if len(sys.argv) != 2:
        print("Usage: python cpzify.py <directory_path>")
        sys.exit(1)

    root_path = Path(sys.argv[1])
    if not root_path.exists():
        print(f"Error: Path {root_path} does not exist")
        sys.exit(1)

    print(f"Processing directories recursively in: {root_path}")
    success_count, error_count = process_directory_recursively(root_path)

    print(f"\nConversion complete!")
    print(f"Successfully processed: {success_count} directories")
    if error_count > 0:
        print(f"Errors encountered: {error_count} directories")

if __name__ == "__main__":
    main()
