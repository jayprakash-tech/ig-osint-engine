# IG-OSINT-ENGINE

Advanced modular Instagram OSINT intelligence engine for ethical security research.

## Features

- **Graph Matrix**: Network mapping, mutual connection analysis, community detection
- **Temporal Profiler**: Activity heatmaps, timezone inference, behavioral patterns
- **GeoOSINT**: EXIF extraction, GPS tracking, device fingerprinting
- **Change Detection**: Monitor deleted posts, bio changes, follower spikes

## Installation

```bash
git clone https://github.com/jayprakash-tech/ig-osint-engine.git
cd ig-osint-engine
pip install -r requirements.txt
```
## Harvest data

```bash
python main.py harvest --username target_user --posts 100 --followers 200
```
## Analyze network

```bash
python main.py analyze --username target_user --graph --temporal
```
## Download media & extract EXIF

```bash
python main.py media --username target_user --download --exif
```
## Monitor changes

```bash
python main.py monitor --username target_user --check
```
## Compare two accounts

```bash
python main.py compare --username1 user1 --username2 user2 --mutual-followers
```

## Rate Limit Defense
Built-in exponential backoff, jittered delays, and session management to handle Instagram's 429 blocks.

## Disclaimer
This tool is for educational and ethical security research only. Comply with Instagram's Terms of Service and applicable laws. The author is not responsible for misuse.

## License
MIT License

--- END README ---
