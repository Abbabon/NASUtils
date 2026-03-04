FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Copy project file and restore dependencies
COPY YoutubeDownloader.csproj .
RUN dotnet restore

# Copy source code and build
COPY . .
RUN dotnet publish -c Release -o /app/publish

# Runtime image
FROM mcr.microsoft.com/dotnet/runtime:8.0 AS runtime
WORKDIR /app

# Install yt-dlp, ffmpeg, and deno (JS runtime required by yt-dlp for YouTube)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    curl \
    unzip \
    && pip3 install yt-dlp \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY --from=build /app/publish .

# Create downloads directory
RUN mkdir -p /app/downloads

# Entry point
ENTRYPOINT ["dotnet", "YoutubeDownloader.dll"]