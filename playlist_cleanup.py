import os
import sys
from pathlib import Path

def try_read_file(file_path, encodings=['utf-8', 'cp1252', 'latin1']):
    """
    Attempts to read a file with different encodings.
    Returns the content and the successful encoding.
    """
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.readlines(), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read file with any of the encodings: {encodings}")

def get_next_backup_number(playlist_path):
    """
    Finds the next available backup number for a playlist file.
    Returns the next number to use.
    """
    base_path = playlist_path.parent / playlist_path.stem
    backup_pattern = base_path.with_suffix('.bak.*')
    existing_backups = list(playlist_path.parent.glob(backup_pattern.name))
    
    if not existing_backups:
        return 1
    
    # Extract numbers from existing backups and find the highest
    numbers = []
    for backup in existing_backups:
        try:
            num = int(backup.suffix.split('.')[-1])
            numbers.append(num)
        except (ValueError, IndexError):
            continue
    
    return max(numbers) + 1 if numbers else 1

def is_playlist_file(file_path):
    """
    Checks if the file is a playlist file (.m3u or .m3u8)
    """
    return file_path.suffix.lower() in ['.m3u', '.m3u8']

def clean_playlist(playlist_path, remove_prefix="E:\\FLAC"):
    """
    Cleans up a playlist file (.m3u or .m3u8) by removing specified prefix from file paths.
    Creates a backup of the original file with a numbered extension.
    Returns tuple of (success, number of paths processed)
    """
    try:
        playlist_path = Path(playlist_path)
        if not playlist_path.exists():
            print(f"Error: {playlist_path} does not exist")
            return False, 0

        if not is_playlist_file(playlist_path):
            print(f"Error: {playlist_path} is not a playlist file (.m3u or .m3u8)")
            return False, 0

        # Read the original playlist with multiple encoding attempts
        try:
            lines, used_encoding = try_read_file(playlist_path)
            print(f"Successfully read file using {used_encoding} encoding")
        except ValueError as e:
            print(f"Error reading {playlist_path}: {str(e)}")
            return False, 0

        # Create backup filename
        backup_number = get_next_backup_number(playlist_path)
        backup_path = playlist_path.with_suffix(f'.bak.{backup_number}')

        # Create backup of original file
        import shutil
        shutil.copy2(playlist_path, backup_path)
        print(f"Created backup: {backup_path}")

        # Process and write the cleaned playlist
        processed_count = 0
        with open(playlist_path, 'w', encoding='utf-8') as f:
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    # Preserve comments and empty lines
                    f.write(line + '\n')
                    continue

                # Remove the prefix if it exists
                if line.startswith(remove_prefix):
                    cleaned_line = line[len(remove_prefix):].lstrip('\\/')
                    f.write(cleaned_line + '\n')
                else:
                    f.write(line + '\n')
                processed_count += 1

        print(f"Successfully updated playlist: {playlist_path}")
        print(f"Processed {processed_count} paths")
        return True, processed_count

    except Exception as e:
        print(f"Error processing {playlist_path}: {str(e)}")
        return False, 0

def process_directory(directory_path, remove_prefix="E:\\FLAC"):
    """
    Processes all playlist files (.m3u and .m3u8) in a directory and its subdirectories.
    Returns tuple of (success_count, error_count)
    """
    directory_path = Path(directory_path)
    if not directory_path.is_dir():
        print(f"Error: {directory_path} is not a directory")
        return 0, 1

    success_count = 0
    error_count = 0

    # Process all playlist files in the directory and subdirectories
    for playlist_path in directory_path.rglob("*"):
        # Skip backup files and non-playlist files
        if playlist_path.suffix.startswith('.bak') or not is_playlist_file(playlist_path):
            continue
            
        print(f"\nProcessing playlist: {playlist_path}")
        success, _ = clean_playlist(playlist_path, remove_prefix)
        if success:
            success_count += 1
        else:
            error_count += 1

    return success_count, error_count

def main():
    if len(sys.argv) < 2:
        print("Usage: python playlist_cleanup.py <directory_path> [prefix_to_remove]")
        sys.exit(1)

    directory_path = Path(sys.argv[1])
    prefix_to_remove = sys.argv[2] if len(sys.argv) > 2 else "E:\\FLAC"

    print(f"Processing all playlists in: {directory_path}")
    print(f"Removing prefix: {prefix_to_remove}")
    
    success_count, error_count = process_directory(directory_path, prefix_to_remove)
    
    print(f"\nProcessing complete!")
    print(f"Successfully processed: {success_count} playlists")
    if error_count > 0:
        print(f"Errors encountered: {error_count} playlists")
        sys.exit(1)

if __name__ == "__main__":
    main() 