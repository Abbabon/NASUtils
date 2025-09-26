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

# Install yt-dlp and ffmpeg
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    && pip3 install yt-dlp \
    && rm -rf /var/lib/apt/lists/*

# Copy application
COPY --from=build /app/publish .

# Create downloads directory
RUN mkdir -p /app/downloads

# Entry point
ENTRYPOINT ["dotnet", "YoutubeDownloader.dll"]