# Wavelink

I built this project to learn how client/server systems behave when you move real data over a network instead of just handling in-memory operations.

The main focus was audio streaming over TCP, SSL/TLS, browser UI integration, buffering behavior, and how to make a small streaming system feel usable while still being understandable.

## What I was trying to learn

- how TCP streams work in practice
- how SSL/TLS changes the data flow and trust model
- how buffering and packet timing affect audio playback
- how a browser UI can talk to a local streaming service
- how to separate server logic, client logic, and UI logic cleanly enough to reason about

## What the project does

This is a small music streaming system with:

- secure TCP audio transfer
- browser-based controls
- playlist management
- audio playback and queue behavior
- basic streaming metadata and monitoring

## Architecture

- `server.py` — main streaming server, SSL layer, and local web interface
- `client.py` — client side that connects to the stream and plays audio
- `index.html`, `style.css`, `app.js` — browser UI
- `music/` — audio files and metadata
- `playlists/` — saved playlist data

## What I learned from building it

The most useful part was not the final application. It was the debugging.

I had to think about:

- what happens when chunks arrive late or out of order
- how playback smoothness changes when buffering is too small or too large
- how encryption changes the trust boundaries between server and client
- why a listening script and a browser UI can look fine individually but behave differently together

## What went wrong or surprised me

One of the biggest surprises was how much the system depends on timing. A streaming app that seems simple on the surface becomes much more complex when you start thinking about chunk delivery, buffering, and UI responsiveness together.

I also learned that a project can look “finished” while still being very rough in terms of real-world reliability. This version is good as a learning project, but it would need more work before I would treat it as a production-like system.

## How to run

See [INSTALLATION.md](INSTALLATION.md) for setup details.

Typical flow:

```bash
python server.py
python client.py
```

## What I would do differently now

- split the networking logic from playback logic more cleanly
- make the buffering system easier to reason about
- add more explicit monitoring and recovery states
- improve the playlist and metadata design
- make validation and testing easier for edge cases

## Current takeaway

This project is a good example of practical systems learning: networking, timing, security, and UI all meet in one place. It is not just a demo — it is a project where I learned how much engineering a streaming app really involves.
