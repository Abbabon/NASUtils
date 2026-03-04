using System.Diagnostics;
using System.Text.RegularExpressions;
using System.Text.Json;

namespace YoutubeDownloader;

class Program
{
    private static readonly Dictionary<string, string> LanguageMappings = new()
    {
        {"en", "English"}, {"es", "Spanish"}, {"fr", "French"}, {"de", "German"}, 
        {"it", "Italian"}, {"pt", "Portuguese"}, {"ru", "Russian"}, {"zh", "Chinese"}, 
        {"ja", "Japanese"}, {"ko", "Korean"}, {"ar", "Arabic"}, {"hi", "Hindi"},
        {"he", "Hebrew"}, {"iw", "Hebrew"}, {"nl", "Dutch"}, {"sv", "Swedish"}, 
        {"no", "Norwegian"}, {"da", "Danish"}, {"fi", "Finnish"}, {"pl", "Polish"}, 
        {"cs", "Czech"}, {"sk", "Slovak"}, {"hu", "Hungarian"}, {"ro", "Romanian"}, 
        {"bg", "Bulgarian"}, {"hr", "Croatian"}, {"sr", "Serbian"}, {"sl", "Slovenian"}, 
        {"et", "Estonian"}, {"lv", "Latvian"}, {"lt", "Lithuanian"}, {"uk", "Ukrainian"}, 
        {"be", "Belarusian"}, {"mk", "Macedonian"}, {"sq", "Albanian"}, {"el", "Greek"}, 
        {"tr", "Turkish"}, {"ca", "Catalan"}, {"eu", "Basque"}, {"gl", "Galician"}, 
        {"cy", "Welsh"}, {"ga", "Irish"}, {"is", "Icelandic"}, {"mt", "Maltese"}, 
        {"th", "Thai"}, {"vi", "Vietnamese"}, {"id", "Indonesian"}, {"ms", "Malay"}, 
        {"tl", "Filipino"}, {"sw", "Swahili"}, {"am", "Amharic"}, {"yo", "Yoruba"}, 
        {"zu", "Zulu"}, {"af", "Afrikaans"}, {"fa", "Persian"}, {"ur", "Urdu"}, 
        {"bn", "Bengali"}, {"ta", "Tamil"}, {"te", "Telugu"}, {"kn", "Kannada"}, 
        {"ml", "Malayalam"}, {"mr", "Marathi"}, {"gu", "Gujarati"}, {"pa", "Punjabi"}, 
        {"ne", "Nepali"}, {"si", "Sinhala"}, {"my", "Burmese"}, {"km", "Khmer"}, 
        {"lo", "Lao"}, {"ka", "Georgian"}, {"hy", "Armenian"}, {"az", "Azerbaijani"}, 
        {"kk", "Kazakh"}, {"ky", "Kyrgyz"}, {"uz", "Uzbek"}, {"tk", "Turkmen"}, 
        {"mn", "Mongolian"}, {"bo", "Tibetan"}, {"dz", "Dzongkha"}
    };

    private static readonly string[] PopularSubtitleLanguages = 
    {
        "en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko", "ar", "hi"
    };

    static async Task<int> Main(string[] args)
    {
        if (args.Length == 0)
        {
            Console.WriteLine("Usage: dotnet run <url> [output-directory] [--items <selection>]");
            Console.WriteLine("  url: YouTube video or playlist URL");
            Console.WriteLine("  output-directory: Directory to save files (default: downloads)");
            Console.WriteLine("  --items: Download specific playlist items (e.g. 1, 1,3,5, 2-7, 1,3-5,8)");
            return 1;
        }

        // Parse args: url is first non-flag arg, output-dir is second, --items is named
        string url = args[0];
        string outputDir = "downloads";
        string? itemsSpec = null;

        for (int i = 1; i < args.Length; i++)
        {
            if (args[i] == "--items" && i + 1 < args.Length)
            {
                itemsSpec = args[++i];
            }
            else if (!args[i].StartsWith("--"))
            {
                outputDir = args[i];
            }
        }

        try
        {
            var downloader = new YoutubeDownloader();
            if (downloader.IsPlaylistUrl(url))
            {
                HashSet<int>? selectedItems = null;
                if (itemsSpec != null)
                    selectedItems = ParseItemSelection(itemsSpec);
                await downloader.DownloadPlaylistAsync(url, outputDir, selectedItems);
            }
            else
            {
                if (itemsSpec != null)
                    Console.WriteLine("Warning: --items is ignored for single video URLs.");
                await downloader.DownloadVideoAsync(url, outputDir);
            }
            return 0;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error: {ex.Message}");
            return 1;
        }
    }

    /// <summary>
    /// Parses item selection string like "1", "1,3,5", "2-7", "1,3-5,8" into a set of 1-based indices.
    /// </summary>
    static HashSet<int> ParseItemSelection(string spec)
    {
        var indices = new HashSet<int>();
        foreach (var part in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var trimmed = part.Trim();
            if (trimmed.Contains('-'))
            {
                var rangeParts = trimmed.Split('-', 2);
                if (int.TryParse(rangeParts[0].Trim(), out int start) &&
                    int.TryParse(rangeParts[1].Trim(), out int end))
                {
                    for (int n = start; n <= end; n++)
                        indices.Add(n);
                }
                else
                {
                    Console.WriteLine($"Warning: could not parse range '{trimmed}', skipping.");
                }
            }
            else if (int.TryParse(trimmed, out int index))
            {
                indices.Add(index);
            }
            else
            {
                Console.WriteLine($"Warning: could not parse item '{trimmed}', skipping.");
            }
        }

        if (indices.Count == 0)
            throw new Exception($"No valid items in selection: {spec}");

        return indices;
    }

    public class YoutubeDownloader
    {
        public async Task<DownloadResult> DownloadVideoAsync(string url, string outputDir)
        {
            string videoId = ExtractVideoId(url);
            string videoDir = Path.Combine(outputDir, videoId);
            string tempDir = Path.Combine(videoDir, "temp");

            Directory.CreateDirectory(videoDir);
            Directory.CreateDirectory(tempDir);

            Console.WriteLine($"Downloading to: {videoDir}");

            // Check if already downloaded
            if (Directory.GetFiles(videoDir, "*.mkv").Length > 0)
            {
                Console.WriteLine($"Video already downloaded in {videoDir}");
                Console.WriteLine("Skipping download. Delete the folder to re-download.");
                return DownloadResult.Skipped;
            }

            // Fetch formats
            Console.WriteLine("Fetching formats...");
            var formatInfo = await GetVideoFormatsAsync(url);

            var bestVideo = GetBestVideoFormat(formatInfo.VideoFormats);
            var uniqueAudioTracks = GetUniqueAudioTracks(formatInfo.AudioFormats);

            if (bestVideo == null || !uniqueAudioTracks.Any())
            {
                throw new Exception("Could not detect video or audio formats");
            }

            Console.WriteLine($"Best video format: {bestVideo.Id}");
            Console.WriteLine($"Found {uniqueAudioTracks.Count} unique audio languages");

            foreach (var track in uniqueAudioTracks)
            {
                string langName = LanguageMappings.GetValueOrDefault(track.Language, track.Language);
                Console.WriteLine($"  {track.Language} ({langName}): {track.Id}");
            }

            try
            {
                await DownloadWithYtDlpAsync(url, bestVideo, uniqueAudioTracks, tempDir, videoDir, withSubtitles: true);
            }
            catch
            {
                Console.WriteLine("Download failed, retrying without subtitles...");
                if (Directory.Exists(tempDir))
                    Directory.Delete(tempDir, true);
                Directory.CreateDirectory(tempDir);
                await DownloadWithYtDlpAsync(url, bestVideo, uniqueAudioTracks, tempDir, videoDir, withSubtitles: false);
            }
            return DownloadResult.Success;
        }

        public bool IsPlaylistUrl(string url)
        {
            return url.Contains("playlist?list=") || url.Contains("&list=") || url.Contains("?list=");
        }

        public async Task<(string Title, List<PlaylistEntry> Entries)> GetPlaylistVideosAsync(string url)
        {
            var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "yt-dlp",
                    Arguments = $"--flat-playlist -J \"{url}\"",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };

            process.Start();
            string output = await process.StandardOutput.ReadToEndAsync();
            string stderr = await process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();

            if (process.ExitCode != 0)
            {
                string errorDetail = stderr.Trim();
                throw new Exception($"Failed to fetch playlist information: {errorDetail}");
            }

            using var doc = JsonDocument.Parse(output);
            var root = doc.RootElement;

            string playlistTitle = root.TryGetProperty("title", out var titleProp)
                ? titleProp.GetString() ?? "Unknown Playlist"
                : "Unknown Playlist";

            var entries = new List<PlaylistEntry>();
            if (root.TryGetProperty("entries", out var entriesArray))
            {
                foreach (var entry in entriesArray.EnumerateArray())
                {
                    string videoId = entry.TryGetProperty("id", out var idProp)
                        ? idProp.GetString() ?? "" : "";
                    string title = entry.TryGetProperty("title", out var tProp)
                        ? tProp.GetString() ?? "Unknown" : "Unknown";

                    if (!string.IsNullOrEmpty(videoId))
                    {
                        entries.Add(new PlaylistEntry { VideoId = videoId, Title = title });
                    }
                }
            }

            return (playlistTitle, entries);
        }

        public async Task DownloadPlaylistAsync(string url, string outputDir, HashSet<int>? selectedItems = null)
        {
            Console.WriteLine("Fetching playlist information...");
            var (playlistTitle, entries) = await GetPlaylistVideosAsync(url);

            string playlistId = ExtractPlaylistId(url);
            string playlistDir = Path.Combine(outputDir, playlistId);
            Directory.CreateDirectory(playlistDir);

            Console.WriteLine($"Playlist: {playlistTitle}");
            Console.WriteLine($"Total videos in playlist: {entries.Count}");
            Console.WriteLine($"Output folder: {playlistDir}");

            if (entries.Count == 0)
            {
                Console.WriteLine("Playlist is empty, nothing to download.");
                return;
            }

            // Validate selected items against playlist size
            if (selectedItems != null)
            {
                var outOfRange = selectedItems.Where(i => i < 1 || i > entries.Count).ToList();
                if (outOfRange.Any())
                    Console.WriteLine($"Warning: items out of range (1-{entries.Count}), will be skipped: {string.Join(", ", outOfRange)}");

                int validCount = selectedItems.Count(i => i >= 1 && i <= entries.Count);
                Console.WriteLine($"Downloading {validCount} of {entries.Count} videos");
            }

            Console.WriteLine();

            int succeeded = 0;
            int skipped = 0;
            var failed = new List<(int Index, string Title, string Error)>();
            int padWidth = entries.Count.ToString().Length;
            bool isFirst = true;

            for (int i = 0; i < entries.Count; i++)
            {
                int itemNumber = i + 1;

                // Skip items not in selection
                if (selectedItems != null && !selectedItems.Contains(itemNumber))
                    continue;

                var entry = entries[i];
                string prefix = itemNumber.ToString().PadLeft(padWidth, '0');

                // Rate limiting delay between videos (skip before first)
                if (!isFirst)
                {
                    Console.WriteLine("Waiting 5 seconds before next video...");
                    await Task.Delay(5000);
                    Console.WriteLine();
                }
                isFirst = false;

                Console.WriteLine($"[{itemNumber}/{entries.Count}] {entry.Title}");

                // Check if already downloaded to playlist folder
                var existingFiles = Directory.GetFiles(playlistDir, "*.mkv")
                    .Where(f => Path.GetFileName(f).Contains(entry.VideoId));
                if (existingFiles.Any())
                {
                    Console.WriteLine($"  Already downloaded in playlist folder, skipping.");
                    skipped++;
                    continue;
                }

                try
                {
                    var result = await DownloadVideoAsync(entry.Url, playlistDir);
                    if (result == DownloadResult.Skipped)
                    {
                        // MKV exists in videoId subfolder (e.g. interrupted previous run)
                        skipped++;
                    }
                    else
                    {
                        succeeded++;
                    }

                    // Move MKV from videoId subfolder to playlist folder with number prefix
                    string videoSubDir = Path.Combine(playlistDir, entry.VideoId);
                    if (Directory.Exists(videoSubDir))
                    {
                        var mkvFiles = Directory.GetFiles(videoSubDir, "*.mkv");
                        foreach (var mkv in mkvFiles)
                        {
                            string numberedName = $"{prefix}. {Path.GetFileName(mkv)}";
                            string destPath = Path.Combine(playlistDir, numberedName);
                            File.Move(mkv, destPath);
                            Console.WriteLine($"  Moved: {numberedName}");
                        }
                        Directory.Delete(videoSubDir, true);
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"  Failed: {ex.Message}");
                    failed.Add((itemNumber, entry.Title, ex.Message));
                    // Clean up partial videoId subfolder on failure
                    string videoSubDir = Path.Combine(playlistDir, entry.VideoId);
                    if (Directory.Exists(videoSubDir))
                        Directory.Delete(videoSubDir, true);
                }
            }

            Console.WriteLine();

            // Print summary
            Console.WriteLine("=== Playlist Download Summary ===");
            Console.WriteLine($"  Succeeded: {succeeded}");
            Console.WriteLine($"  Skipped:   {skipped}");
            Console.WriteLine($"  Failed:    {failed.Count}");

            if (failed.Count > 0)
            {
                Console.WriteLine();
                Console.WriteLine("Failed videos:");
                foreach (var (index, title, error) in failed)
                {
                    Console.WriteLine($"  - [{index}] {title}: {error}");
                }
                Console.WriteLine();
                Console.WriteLine($"Retry with: --items {string.Join(",", failed.Select(f => f.Index))}");
            }
        }

        private string ExtractPlaylistId(string url)
        {
            var match = Regex.Match(url, @"[?&]list=([^&]+)");
            return match.Success ? match.Groups[1].Value : "playlist";
        }

        private string ExtractVideoId(string url)
        {
            // Extract from ?v= parameter
            var match = Regex.Match(url, @"[?&]v=([^&]*)");
            if (match.Success)
                return match.Groups[1].Value;

            // Extract from youtu.be/ format
            match = Regex.Match(url, @"youtu\.be/([^?]*)");
            if (match.Success)
                return match.Groups[1].Value;

            // Fallback to timestamp
            return DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        }

        private async Task<FormatInfo> GetVideoFormatsAsync(string url)
        {
            var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "yt-dlp",
                    Arguments = $"-F \"{url}\"",
                    RedirectStandardOutput = true,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };

            process.Start();
            string output = await process.StandardOutput.ReadToEndAsync();
            await process.WaitForExitAsync();

            if (process.ExitCode != 0)
                throw new Exception("Failed to fetch video formats");

            return ParseFormats(output);
        }

        private FormatInfo ParseFormats(string output)
        {
            var lines = output.Split('\n');
            var videoFormats = new List<VideoFormat>();
            var audioFormats = new List<AudioFormat>();

            foreach (var line in lines)
            {
                if (line.Contains("video only"))
                {
                    var parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length > 0)
                    {
                        videoFormats.Add(new VideoFormat { Id = parts[0], Quality = line });
                    }
                }
                else if (line.Contains("audio only"))
                {
                    var parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length > 0)
                    {
                        var langMatch = Regex.Match(line, @"\[([^\]]+)\]");
                        string language = langMatch.Success ? langMatch.Groups[1].Value : "unknown";
                        
                        audioFormats.Add(new AudioFormat 
                        { 
                            Id = parts[0], 
                            Language = language,
                            Quality = line 
                        });
                    }
                }
            }

            return new FormatInfo { VideoFormats = videoFormats, AudioFormats = audioFormats };
        }

        private VideoFormat? GetBestVideoFormat(List<VideoFormat> formats)
        {
            return formats.LastOrDefault(); // Last one is usually highest quality
        }

        private List<AudioFormat> GetUniqueAudioTracks(List<AudioFormat> formats)
        {
            var uniqueTracks = new List<AudioFormat>();
            var seenLanguages = new HashSet<string>();

            foreach (var format in formats)
            {
                if (!seenLanguages.Contains(format.Language))
                {
                    uniqueTracks.Add(format);
                    seenLanguages.Add(format.Language);
                }
            }

            return uniqueTracks;
        }

        private async Task DownloadWithYtDlpAsync(string url, VideoFormat video, List<AudioFormat> audioTracks, string tempDir, string outputDir, bool withSubtitles = true)
        {
            var audioIds = string.Join("+", audioTracks.Select(a => a.Id));
            var combinedFormat = $"{video.Id}+{audioIds}";

            var metadataArgs = new List<string>();
            for (int i = 0; i < audioTracks.Count; i++)
            {
                string langName = LanguageMappings.GetValueOrDefault(audioTracks[i].Language, audioTracks[i].Language);
                metadataArgs.Add($"-metadata:s:a:{i} title=\"{langName}\"");
            }

            var subtitleLangs = string.Join(",", PopularSubtitleLanguages);

            var args = $"--no-warnings " +
                       $"-f \"{combinedFormat}\" " +
                       $"--audio-multistreams ";

            if (withSubtitles)
            {
                args += $"--write-subs " +
                        $"--write-auto-subs " +
                        $"--sub-langs \"{subtitleLangs}\" " +
                        $"--embed-subs " +
                        $"--sleep-subtitles 5 ";
            }

            args += $"--merge-output-format mkv " +
                    $"--retries 5 " +
                    $"--fragment-retries 5 " +
                    $"--retry-sleep 10 " +
                    $"--postprocessor-args \"ffmpeg:{string.Join(" ", metadataArgs)}\" " +
                    $"\"{url}\"";

            var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "yt-dlp",
                    Arguments = args,
                    WorkingDirectory = tempDir,
                    UseShellExecute = false,
                    CreateNoWindow = true
                }
            };

            Console.WriteLine($"Starting download with format: {combinedFormat}");
            process.Start();
            await process.WaitForExitAsync();

            if (process.ExitCode != 0)
                throw new Exception("Download failed");

            // Move MKV files to output directory
            var mkvFiles = Directory.GetFiles(tempDir, "*.mkv");
            foreach (var file in mkvFiles)
            {
                var fileName = Path.GetFileName(file);
                var destPath = Path.Combine(outputDir, fileName);
                File.Move(file, destPath);
                Console.WriteLine($"Moved: {fileName}");
            }

            // Clean up
            Directory.Delete(tempDir, true);
            
            // Remove any standalone subtitle files
            var subtitleFiles = Directory.GetFiles(outputDir, "*.vtt")
                .Concat(Directory.GetFiles(outputDir, "*.srt"));
            foreach (var file in subtitleFiles)
            {
                File.Delete(file);
            }

            Console.WriteLine($"Download completed in: {outputDir}");
        }
    }

    public class FormatInfo
    {
        public List<VideoFormat> VideoFormats { get; set; } = new();
        public List<AudioFormat> AudioFormats { get; set; } = new();
    }

    public class VideoFormat
    {
        public string Id { get; set; } = "";
        public string Quality { get; set; } = "";
    }

    public class AudioFormat
    {
        public string Id { get; set; } = "";
        public string Language { get; set; } = "";
        public string Quality { get; set; } = "";
    }

    public enum DownloadResult
    {
        Success,
        Skipped
    }

    public class PlaylistEntry
    {
        public string VideoId { get; set; } = "";
        public string Title { get; set; } = "";
        public string Url => $"https://www.youtube.com/watch?v={VideoId}";
    }
}