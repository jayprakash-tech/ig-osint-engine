# IG-OSINT-ENGINE

Advanced modular Instagram OSINT intelligence engine for ethical security research.

## Features

- **Graph Matrix**: Network mapping, mutual connection analysis, community detection
- **Temporal Profiler**: Activity heatmaps, timezone inference, behavioral patterns
- **GeoOSINT**: EXIF extraction, GPS tracking, device fingerprinting
- **Change Detection**: Monitor deleted posts, bio changes, follower spikes
- **Indirect Recon (Pillar 5)**: bio entity extraction (emails/phones/crypto wallets), high-res avatar, cross-platform username enumeration, reverse image search links, tagged-post discovery — works on private profiles too

## Installation

```bash
git clone https://github.com/jayprakash-tech/ig-osint-engine.git
cd ig-osint-engine
pip install -r requirements.txt
```
## Usage

### Harvest data

```bash
python main.py harvest --username target_user --posts 100 --followers 200
```
### Analyze network

```bash
python main.py analyze --username target_user --graph --temporal
```
### Download media & extract EXIF

```bash
python main.py media --username target_user --download --exif
```
### Monitor changes

```bash
python main.py monitor --username target_user --check
```
### Compare two accounts

```bash
python main.py compare --username1 user1 --username2 user2 --mutual-followers
```
### Pillar 5 indirect recon (private-profile safe)

```bash
python main.py recon --username target_user --cookies cookies.json
```
## Rate Limit Defense
Built-in exponential backoff, jittered delays, and session management to handle Instagram's 429 blocks.

## Disclaimer
This tool is for educational and ethical security research only. Comply with Instagram's Terms of Service and applicable laws. The author is not responsible for misuse.

## Project Layout

    ig-osint-engine/
    ├── main.py              # CLI entry point
    ├── requirements.txt     # dependencies
    ├── install.sh           # one-command setup (Linux + Termux)
    ├── modules/
    │   ├── harvester.py     # collection + rate-limit defense
    │   ├── analyzer.py      # graph + temporal pillars
    │   ├── media_handler.py # CDN download + EXIF/geo
    │   ├── monitor.py       # change detection
    │   └── recon.py         # Pillar 5 indirect recon
    ├── data/                # snapshots (local only, gitignored)
    └── output/              # reports/graphs (local only, gitignored)

## Known Limitations

- Most Instagram endpoints require a logged-in session; unauthenticated use is heavily restricted.
- Follower/following lists are aggressively rate-limited and may return partial data.
- Instagram strips EXIF on upload, so GPS from EXIF is rare; post geotags are the primary geospatial source.
- Instagram may change its API at any time; a failing command usually means an upstream change, not a bug.
- Deleted vs archived posts cannot be distinguished externally, so removals are reported as "possibly deleted."
- Timezone inference is a heuristic estimate, not proof of physical location.
- Only research public accounts you are authorized to analyze, and respect rate limits and Instagram's Terms of Service.


## License
MIT License
