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
            Console.WriteLine("Usage: dotnet run <video-url> [output-directory]");
            Console.WriteLine("  video-url: YouTube URL to download");
            Console.WriteLine("  output-directory: Directory to save files (default: downloads)");
            return 1;
        }

        string url = args[0];
        string outputDir = args.Length > 1 ? args[1] : "downloads";

        try
        {
            var downloader = new YoutubeDownloader();
            await downloader.DownloadVideoAsync(url, outputDir);
            return 0;
        }
        catch (Exception ex)
        {
            Console.WriteLine($"Error: {ex.Message}");
            return 1;
        }
    }

    public class YoutubeDownloader
    {
        public async Task DownloadVideoAsync(string url, string outputDir)
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
                return;
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

            await DownloadWithYtDlpAsync(url, bestVideo, uniqueAudioTracks, tempDir, videoDir);
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

        private async Task DownloadWithYtDlpAsync(string url, VideoFormat video, List<AudioFormat> audioTracks, string tempDir, string outputDir)
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

            var process = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "yt-dlp",
                    Arguments = $"--no-warnings " +
                               $"-f \"{combinedFormat}\" " +
                               $"--audio-multistreams " +
                               $"--write-subs " +
                               $"--write-auto-subs " +
                               $"--sub-langs \"{subtitleLangs}\" " +
                               $"--embed-subs " +
                               $"--merge-output-format mkv " +
                               $"--retries 5 " +
                               $"--fragment-retries 5 " +
                               $"--retry-sleep 10 " +
                               $"--sleep-subtitles 5 " +
                               $"--postprocessor-args \"ffmpeg:{string.Join(" ", metadataArgs)}\" " +
                               $"\"{url}\"",
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
}