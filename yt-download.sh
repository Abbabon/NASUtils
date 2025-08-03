#!/usr/bin/env bash
URL="$1"
OUTPUT_DIR="${2:-downloads}"

if [ -z "$URL" ]; then
  echo "Usage: $0 <video-url> [output-directory]"
  echo "  video-url: YouTube URL to download"
  echo "  output-directory: Directory to save files (default: downloads)"
  exit 1
fi

# Extract video ID from URL for unique folder naming (BSD grep compatible)
VIDEO_ID=$(echo "$URL" | sed -n 's/.*[?&]v=\([^&]*\).*/\1/p')
if [ -z "$VIDEO_ID" ]; then
  VIDEO_ID=$(echo "$URL" | sed -n 's/.*youtu\.be\/\([^?]*\).*/\1/p')
fi
if [ -z "$VIDEO_ID" ]; then
  VIDEO_ID=$(date +%s)  # fallback to timestamp
fi

# Create unique output directory for this video
VIDEO_DIR="$OUTPUT_DIR/$VIDEO_ID"
mkdir -p "$VIDEO_DIR"
TEMP_DIR="$VIDEO_DIR/temp"
mkdir -p "$TEMP_DIR"

echo "Downloading to: $VIDEO_DIR"

# Check if already downloaded
if [ -f "$VIDEO_DIR"/*.mkv ]; then
  echo "Video already downloaded in $VIDEO_DIR"
  echo "Skipping download. Delete the folder to re-download."
  exit 0
fi

# fetch formats
echo "Fetching formats..."
yt-dlp -F "$URL" > formats.txt

echo "Available audio streams:"
grep 'audio only' formats.txt

# extract best quality video format
v_id=$(grep 'video only' formats.txt | tail -n1 | awk '{print $1}')

# Language code to full name mapping
get_language_name() {
  case "$1" in
    "en") echo "English" ;;
    "es") echo "Spanish" ;;
    "fr") echo "French" ;;
    "de") echo "German" ;;
    "it") echo "Italian" ;;
    "pt") echo "Portuguese" ;;
    "ru") echo "Russian" ;;
    "zh") echo "Chinese" ;;
    "ja") echo "Japanese" ;;
    "ko") echo "Korean" ;;
    "ar") echo "Arabic" ;;
    "hi") echo "Hindi" ;;
    "he"|"iw") echo "Hebrew" ;;
    "nl") echo "Dutch" ;;
    "sv") echo "Swedish" ;;
    "no") echo "Norwegian" ;;
    "da") echo "Danish" ;;
    "fi") echo "Finnish" ;;
    "pl") echo "Polish" ;;
    "cs") echo "Czech" ;;
    "sk") echo "Slovak" ;;
    "hu") echo "Hungarian" ;;
    "ro") echo "Romanian" ;;
    "bg") echo "Bulgarian" ;;
    "hr") echo "Croatian" ;;
    "sr") echo "Serbian" ;;
    "sl") echo "Slovenian" ;;
    "et") echo "Estonian" ;;
    "lv") echo "Latvian" ;;
    "lt") echo "Lithuanian" ;;
    "uk") echo "Ukrainian" ;;
    "be") echo "Belarusian" ;;
    "mk") echo "Macedonian" ;;
    "sq") echo "Albanian" ;;
    "el") echo "Greek" ;;
    "tr") echo "Turkish" ;;
    "ca") echo "Catalan" ;;
    "eu") echo "Basque" ;;
    "gl") echo "Galician" ;;
    "cy") echo "Welsh" ;;
    "ga") echo "Irish" ;;
    "is") echo "Icelandic" ;;
    "mt") echo "Maltese" ;;
    "th") echo "Thai" ;;
    "vi") echo "Vietnamese" ;;
    "id") echo "Indonesian" ;;
    "ms") echo "Malay" ;;
    "tl") echo "Filipino" ;;
    "sw") echo "Swahili" ;;
    "am") echo "Amharic" ;;
    "yo") echo "Yoruba" ;;
    "zu") echo "Zulu" ;;
    "af") echo "Afrikaans" ;;
    "fa") echo "Persian" ;;
    "ur") echo "Urdu" ;;
    "bn") echo "Bengali" ;;
    "ta") echo "Tamil" ;;
    "te") echo "Telugu" ;;
    "kn") echo "Kannada" ;;
    "ml") echo "Malayalam" ;;
    "mr") echo "Marathi" ;;
    "gu") echo "Gujarati" ;;
    "pa") echo "Punjabi" ;;
    "ne") echo "Nepali" ;;
    "si") echo "Sinhala" ;;
    "my") echo "Burmese" ;;
    "km") echo "Khmer" ;;
    "lo") echo "Lao" ;;
    "ka") echo "Georgian" ;;
    "hy") echo "Armenian" ;;
    "az") echo "Azerbaijani" ;;
    "kk") echo "Kazakh" ;;
    "ky") echo "Kyrgyz" ;;
    "uz") echo "Uzbek" ;;
    "tk") echo "Turkmen" ;;
    "mn") echo "Mongolian" ;;
    "bo") echo "Tibetan" ;;
    "dz") echo "Dzongkha" ;;
    *) echo "$1" ;;  # Return original code if not found
  esac
}

# extract unique languages and get best audio for each (bash 3.2 compatible)
echo "Analyzing audio streams..."
audio_langs=""
audio_ids=""
metadata_opts=""

# Process each audio line and build language list
track_num=1
while IFS= read -r line; do
  lang=$(echo "$line" | grep -o '\[.*\]' | head -n1 | tr -d '[]')
  if [ -z "$lang" ]; then
    lang="unknown"
  fi
  audio_id=$(echo "$line" | awk '{print $1}')
  
  # Check if we already have this language
  if ! echo "$audio_langs" | grep -q "|$lang|"; then
    # Get the full language name
    lang_name=$(get_language_name "$lang")
    echo "  Found new language: '$lang' ($lang_name), audio ID: $audio_id"
    audio_langs="$audio_langs|$lang|"
    if [ -z "$audio_ids" ]; then
      audio_ids="$audio_id"
    else
      audio_ids="$audio_ids+$audio_id"
    fi
    
    # Add metadata for track title using full language name
    if [ -z "$metadata_opts" ]; then
      metadata_opts="-metadata:s:a:$((track_num-1)) title=\"$lang_name\""
    else
      metadata_opts="$metadata_opts -metadata:s:a:$((track_num-1)) title=\"$lang_name\""
    fi
    track_num=$((track_num + 1))
  fi
done < <(grep 'audio only' formats.txt)

echo "Language detection complete. Found languages: $(echo "$audio_langs" | tr '|' ' ')"

if [ -z "$v_id" ] || [ -z "$audio_ids" ]; then
  echo "Could not detect video or audio formats"
  exit 1
fi

combined_ids="$v_id+$audio_ids"

echo "Best video format: $v_id"
echo "Audio format string: $audio_ids"
echo "Final download format string: $combined_ids"
echo "Metadata options: $metadata_opts"
audio_count=$(echo "$audio_ids" | tr '+' '\n' | wc -l)
echo "This will download 1 video track + $audio_count audio tracks with language titles"

# Change to temp directory for download
cd "$TEMP_DIR"

# Popular subtitle languages (manually curated to avoid 100+ auto-generated ones)
POPULAR_LANGS="en,es,fr,de,it,pt,ru,zh,ja,ko,ar,hi"

yt-dlp \
  --no-warnings \
  -f "$combined_ids" \
  --audio-multistreams \
  --write-subs \
  --write-auto-subs \
  --sub-langs "$POPULAR_LANGS" \
  --embed-subs \
  --merge-output-format mkv \
  --retries 5 \
  --fragment-retries 5 \
  --retry-sleep 10 \
  --sleep-subtitles 5 \
  --postprocessor-args "ffmpeg:$metadata_opts" \
  "$URL"

# Move completed files to output directory
echo "Moving files to output directory..."
echo "Files in temp directory:"
ls -la

# Only move the MKV file (subtitles are embedded)
mv *.mkv "../" 2>/dev/null || echo "No .mkv files to move"

echo "Final files in output directory:"
cd ".."
ls -la *.mkv 2>/dev/null || echo "No video files found"

# Clean up temp directory and any remaining subtitle files
rm -rf temp/
rm -f *.vtt *.srt 2>/dev/null

echo "Cleanup completed. Final contents:"
ls -la
echo "Download completed in: $VIDEO_DIR"