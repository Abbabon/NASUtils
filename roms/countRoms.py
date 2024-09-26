import os
import sys
from collections import defaultdict

def count_files_by_extensions(path, extensions):
    counts = defaultdict(int)
    for root, dirs, files in os.walk(path):
        for file in files:
            file_lower = file.lower()
            for ext in extensions:
                if file_lower.endswith(ext.lower()):
                    counts[ext] += 1
                    break  # Count the file only once if it matches multiple extensions
    return counts

def main():
    if len(sys.argv) < 3:
        print("Usage: python countRoms.py <path> <extension1> [extension2] ...")
        sys.exit(1)

    path = sys.argv[1]
    extensions = sys.argv[2:]

    if not os.path.isdir(path):
        print(f"Error: '{path}' is not a valid directory.")
        sys.exit(1)

    counts = count_files_by_extensions(path, extensions)

    print(f"File counts in '{path}':")
    for ext, count in counts.items():
        print(f"  {ext}: {count}")

    total_count = sum(counts.values())
    print(f"Total files: {total_count}")

if __name__ == "__main__":
    main()
