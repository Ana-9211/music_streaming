# WAVELINK Installation Guide

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git (optional, for cloning the repository)

## Installation Steps

### 1. Clone or Download the Repository

```bash
git clone https://github.com/Ana-9211/music_streaming.git
cd music_streaming
```

Or download as ZIP and extract.

### 2. Create a Virtual Environment (Recommended)

```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install:
- Flask (web framework)
- Cryptography (SSL/TLS support)
- Sounddevice (audio playback)
- NumPy (audio processing)
- Pycaw (Windows audio control, Windows only)

### 4. Prepare Music Files

Place your WAV files in the `music/` directory:

```
music/
├── Song Title.wav
├── Song Title.jpg
└── ...
```

The `.jpg` files are album artwork displayed in the UI.

### 5. Set Up Song Tags (Optional)

Edit `song_tags.json` to organize songs by genre:

```json
{
  "Elektronomia - Sky High.wav": "Electronic",
  "OneRepublic - Counting Stars.wav": "Pop",
  "TheFatRat - Oblivion.wav": "Electronic"
}
```

### 6. Run the Server

```bash
python server.py
```

**Output:**
```
 * Running on https://127.0.0.1:9894
Listening for audio clients on port 9893...
```

The first run will automatically generate SSL certificates (`server.crt` and `server.key`).

### 7. Run the Client (In Another Terminal)

```bash
python client.py
```

**Output:**
```
Connecting to 127.0.0.1:9893 (secure SSL/TLS)...
Connected! Streaming ready.
Opening browser interface...
```

A browser window will open with the playback UI.

## Troubleshooting

### "Module not found" errors

Ensure you've installed all dependencies:
```bash
pip install -r requirements.txt
```

### "Connection refused" on client startup

Make sure the server is running before starting the client.

### Audio not playing (Windows)

Windows audio control requires `pycaw`. Install via:
```bash
pip install pycaw comtypes
```

### SSL Certificate errors

Delete `server.crt` and `server.key` to regenerate:
```bash
rm server.crt server.key
python server.py
```

### Port already in use

Change the port in the source code:
- `STREAM_PORT` in `server.py` (default: 9893)
- `WEB_PORT` in `server.py` (default: 9894)

## Usage

### Server Interface

Navigate to `http://localhost:9894` to see:
- Connected clients
- Current playlist
- Song information
- Web-based song browser

### Client Interface

The client opens a Spotify-inspired web UI with:
- **Playlists**: Create and manage playlists
- **Queue**: View and reorder upcoming songs
- **Controls**: Play, pause, next, prev, shuffle, loop
- **Volume**: Adjust playback volume and mute
- **Stats**: Monitor connection latency and throughput
- **Modes**: Toggle between demo and smooth buffering

### Keyboard Shortcuts

- **Space**: Play/Pause
- **N**: Next song
- **P**: Previous song
- **L**: Toggle loop
- **S**: Toggle shuffle
- **M**: Toggle mute

## Network Configuration

### Local Network Access

To connect from another computer on the same network:

1. Find your server's IP address:
   ```bash
   # Windows
   ipconfig

   # macOS/Linux
   ifconfig
   ```

2. In client, change connection to server IP instead of `127.0.0.1`

### Remote Access (Not Recommended)

For security reasons, do NOT expose this server to the internet without:
- Proper firewall configuration
- Authentication system
- Certificate pinning

## Performance Optimization

### Chunk Size Adjustment

In `server.py`, modify `CHUNK_SIZE` (default: 4096):
- Smaller = lower latency, more network overhead
- Larger = higher latency, less overhead

### Buffer Settings

In `client.py`, adjust buffering parameters:
- Demo mode: Fixed-size buffer (good for testing)
- Smooth mode: Adaptive buffer (better for real-world use)

### Network Tuning

For high-latency networks, increase buffer size in client.

## Support

For issues or questions, check the README.md file or review the comments in the source code.
