# WAVELINK - SSL/TCP Audio Streaming Server

A sophisticated music streaming application with encrypted audio transmission, featuring a Flask-based web UI and advanced playback controls.

## Features

- **Secure Streaming**: SSL/TLS encrypted TCP audio streaming with SHA-256 certificates
- **Audio Format**: WAV file support with configurable chunking
- **Playlist Management**: Create, save, and load playlists
- **Playback Controls**: Play, pause, skip, shuffle, loop, and volume control
- **Queue System**: Dynamic queue management with prev/next navigation
- **Live Stats**: Monitor latency, throughput, chunk count, and audio underruns
- **Genre Tagging**: Organize music with custom genre tags
- **Buffering Modes**: Demo mode and smooth mode for optimal playback
- **Web UI**: Spotify-inspired dark theme interface
- **Multi-Client Support**: Up to 5 concurrent clients

## Architecture

### Components

- **Server** (`server.py`): Listens on TCP port 9893, streams WAV files with SSL encryption. Web monitor on port 9894.
- **Client** (`client.py`): Connects over SSL, receives audio stream, plays via sounddevice with volume control.
- **Web UI** (`index.html`, `style.css`, `app.js`): Browser-based interface for playlist management and playback control.

### Configuration

- `STREAM_PORT`: 9893 (Audio streaming)
- `WEB_PORT`: 9894 (Flask web monitor)
- `CHUNK_SIZE`: 4096 bytes
- `MAX_CLIENTS`: 5 concurrent connections

## Installation

See [INSTALLATION.md](INSTALLATION.md) for detailed setup instructions.

## Quick Start

### Start the Server
```bash
python server.py
```

The server will:
- Generate SSL certificates if not present
- Start listening for connections on port 9893
- Launch a web monitor on http://localhost:9894

### Start the Client
```bash
python client.py
```

The client will:
- Connect to the server via SSL/TCP
- Open a browser window with the playback UI
- Stream and play audio in real-time

## Music Directory Structure

```
music/
├── Song Name.wav          # Audio file
└── Song Name.jpg          # Album artwork

playlists/
└── playlist_name.json     # Saved playlists

song_tags.json             # Genre/metadata tags
```

## File Descriptions

- `server.py` - Main server with SSL streaming and Flask web interface
- `client.py` - Client with audio playback and buffering logic
- `app.js` - Frontend playback control and UI state management
- `index.html` - Web interface template
- `style.css` - Spotify-inspired UI styling
- `server.crt`, `server.key` - SSL/TLS certificates (auto-generated)
- `song_tags.json` - Genre and metadata mappings for songs

## Dependencies

See `requirements.txt` for Python dependencies:
- flask
- cryptography
- sounddevice
- numpy
- pycaw (Windows audio control)

## Security

- All audio transmission is encrypted with SHA-256 SSL/TLS
- Certificates auto-generated on first run if not present
- Private key stored locally and never transmitted

## Performance

- Adaptive buffering with demo and smooth modes
- Real-time throughput and latency monitoring
- Automatic underrun detection and recovery
- Efficient chunk-based streaming

## License

MIT License - See LICENSE file for details

## Author

Ana-9211
