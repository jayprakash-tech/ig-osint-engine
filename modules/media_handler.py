"""Instagram Media Handler Module - Pillar 3: GeoOSINT & EXIF.

Downloads public CDN media with throttling and safety guards, extracts
EXIF/GPS metadata, and builds chronological location timelines.

Honest note: Instagram strips EXIF on upload. GPS from EXIF is rare on
Instagram images; post geotags are the primary geospatial source. The
extractor remains fully useful for original/local camera files.
"""

import csv
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import exifread
import requests
from PIL import Image

ALLOWED_CDN_SUFFIXES = ("cdninstagram.com", "fbcdn.net", "instagram.com")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov"}
MAX_BYTES = 200 * 1024 * 1024  # 200 MB safety cap per file


class MediaDownloader:
    """Throttled, guarded bulk downloader for Instagram CDN media."""

    def __init__(self, base_dir: str = "~/ig_toolkit"):
        self.base_dir = Path(base_dir).expanduser()
        self.media_dir = self.base_dir / "data" / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.min_delay = 1.5
        self.max_delay = 4.0
        self.max_retries = 3
        self.timeout = 30
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            "Referer": "https://www.instagram.com/",
        })

    def _delay(self):
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    @staticmethod
    def _is_allowed_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and any(
            host == s or host.endswith("." + s) for s in ALLOWED_CDN_SUFFIXES
        )

    @staticmethod
    def _safe_name(name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:80] or "media"

    def download_media(self, url: str, filename: str,
                       username: str = "unknown") -> Optional[str]:
        if not self._is_allowed_url(url):
            print(f"[MEDIA] Refused non-CDN url: {url[:60]}")
            return None
        user_dir = self.media_dir / self._safe_name(username)
        user_dir.mkdir(parents=True, exist_ok=True)
        filepath = user_dir / self._safe_name(filename)
        if filepath.exists():
            return str(filepath)

        for attempt in range(self.max_retries):
            self._delay()
            try:
                with self.session.get(url, stream=True, timeout=self.timeout) as resp:
                    if resp.status_code == 429:
                        wait = 5.0 * (2 ** attempt)
                        print(f"[MEDIA] 429 - waiting {wait:.0f}s")
                        time.sleep(wait)
                        continue
                    if resp.status_code in (403, 404, 410):
                        print("[MEDIA] CDN link expired or forbidden "
                              "(links are time-limited; re-harvest posts).")
                        return None
                    if resp.status_code != 200:
                        time.sleep(2 ** attempt)
                        continue
                    size = 0
                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError("file exceeds 200 MB cap")
                            f.write(chunk)
                if size == 0:
                    filepath.unlink()
                    return None
                print(f"[MEDIA] Downloaded {filepath.name} ({size:,} bytes)")
                return str(filepath)
            except (requests.RequestException, OSError, ValueError) as exc:
                if filepath.exists():
                    filepath.unlink()
                print(f"[MEDIA] Attempt {attempt + 1} failed: {exc}")
                time.sleep(2 ** attempt * random.uniform(1, 3))
        return None

    def batch_download_posts(self, posts_list: List[Dict],
                             username: str = "unknown") -> List[Dict]:
        user_dir = self.media_dir / self._safe_name(username)
        user_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = user_dir / "download_manifest.json"
        manifest: Dict = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except (ValueError, OSError):
                manifest = {}

        results = []
        print(f"[MEDIA] Batch download: {len(posts_list)} posts")
        for i, post in enumerate(posts_list):
            is_video = bool(post.get("is_video"))
            url = post.get("video_url") if is_video else post.get("display_url")
            short = self._safe_name(post.get("shortcode") or f"post_{i}")
            filename = short + (".mp4" if is_video else ".jpg")
            entry = {
                "post_id": post.get("id"),
                "shortcode": post.get("shortcode"),
                "success": False,
                "path": None,
            }
            if url:
                path = self.download_media(url, filename, username)
                if path:
                    entry["success"] = True
                    entry["path"] = path
                    manifest[str(post.get("id"))] = {
                        "path": path,
                        "shortcode": post.get("shortcode"),
                        "timestamp": post.get("timestamp"),
                        "is_video": is_video,
                        "location": post.get("location"),
                        "downloaded_at": datetime.now(timezone.utc).isoformat(),
                    }
            results.append(entry)

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        ok = sum(1 for r in results if r["success"])
        print(f"[MEDIA] Complete: {ok}/{len(results)} successful")
        return results

    def get_download_statistics(self, username: str = "unknown") -> Dict:
        user_dir = self.media_dir / self._safe_name(username)
        if not user_dir.exists():
            return {"error": "No media directory found"}
        files = [p for p in user_dir.iterdir()
                 if p.is_file() and p.suffix.lower() != ".json"]
        images = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
        videos = [p for p in files if p.suffix.lower() in VIDEO_EXTS]
        total = sum(p.stat().st_size for p in files)
        return {
            "total_files": len(files),
            "images": len(images),
            "videos": len(videos),
            "total_size_mb": round(total / (1024 * 1024), 2),
            "directory": str(user_dir),
        }


class EXIFExtractor:
    """EXIF/GPS extraction with correct rational parsing + geotag timelines."""

    def __init__(self):
        self.extracted_data: List[Dict] = []

    @staticmethod
    def _ratio_to_float(value) -> float:
        """Handle exifread IFDRational / Ratio / 'num/den' across versions."""
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        num = getattr(value, "num", None)
        den = getattr(value, "den", None)
        if num is not None and den:
            return float(num) / float(den)
        if isinstance(value, (tuple, list)) and len(value) == 2 and value[1]:
            return float(value[0]) / float(value[1])
        text = str(value)
        if "/" in text:
            a, b = text.split("/", 1)
            return float(a) / float(b)
        return float(text)

    @classmethod
    def _gps_to_decimal(cls, tags: Dict) -> Optional[Dict]:
        try:
            lat_tag = tags.get("GPS GPSLatitude")
            lon_tag = tags.get("GPS GPSLongitude")
            if lat_tag is None or lon_tag is None:
                return None
            lat_vals = list(lat_tag.values)
            lon_vals = list(lon_tag.values)
            if len(lat_vals) < 3 or len(lon_vals) < 3:
                return None
            lat = sum(cls._ratio_to_float(v) / d
                      for v, d in zip(lat_vals[:3], (1, 60, 3600)))
            lon = sum(cls._ratio_to_float(v) / d
                      for v, d in zip(lon_vals[:3], (1, 60, 3600)))
            if str(tags.get("GPS GPSLatitudeRef", "N")).strip().upper() == "S":
                lat = -lat
            if str(tags.get("GPS GPSLongitudeRef", "E")).strip().upper() == "W":
                lon = -lon
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            return {"latitude": round(lat, 6), "longitude": round(lon, 6)}
        except (TypeError, ValueError, ZeroDivisionError, AttributeError):
            return None

    def extract_exif_from_image(self, image_path: str) -> Dict:
        try:
            with Image.open(image_path) as img:
                basic = {"format": img.format, "width": img.width,
                         "height": img.height, "mode": img.mode}
            with open(image_path, "rb") as f:
                tags = exifread.process_file(f, details=False)
            device = {k: str(tags[k]) for k in
                      ("Image Make", "Image Model", "Image Software", "EXIF LensModel")
                      if k in tags}
            exif_dt = None
            for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
                if key in tags:
                    try:
                        exif_dt = datetime.strptime(
                            str(tags[key]).strip(), "%Y:%m:%d %H:%M:%S")
                        break
                    except ValueError:
                        continue
            data = {
                "file_path": str(image_path),
                "basic_info": basic,
                "device_info": device,
                "exif_datetime": exif_dt.isoformat() if exif_dt else None,
                "gps_coordinates": self._gps_to_decimal(tags),
                "tag_count": len(tags),
                "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.extracted_data.append(data)
            return data
        except Exception as exc:
            return {"error": str(exc), "file_path": str(image_path)}

    def batch_extract_exif(self, image_paths: List[str]) -> List[Dict]:
        results = []
        for path in image_paths:
            p = Path(path)
            if p.exists() and p.suffix.lower() in IMAGE_EXTS:
                results.append(self.extract_exif_from_image(str(p)))
        self.extracted_data = [r for r in results if "error" not in r]
        with_gps = sum(1 for r in self.extracted_data if r.get("gps_coordinates"))
        print(f"[EXIF] Processed {len(self.extracted_data)} images, "
              f"{with_gps} with GPS.")
        print("[EXIF] Note: Instagram strips EXIF on upload - GPS is rare here. "
              "Post geotags are the primary geo source.")
        return results

    def generate_location_timeline(self, posts: Optional[List[Dict]] = None) -> List[Dict]:
        """Merge EXIF GPS entries + post geotags into one chronological timeline."""
        entries = []
        for d in self.extracted_data:
            gps = d.get("gps_coordinates")
            if gps and d.get("exif_datetime"):
                entries.append({
                    "timestamp_utc": d["exif_datetime"],
                    "source": "exif",
                    "latitude": gps["latitude"],
                    "longitude": gps["longitude"],
                    "location_name": None,
                    "reference": d["file_path"],
                })
        for post in posts or []:
            loc = post.get("location") or {}
            lat, lng, ts = loc.get("lat"), loc.get("lng"), post.get("timestamp")
            if lat is None or lng is None or not isinstance(ts, (int, float)):
                continue
            try:
                lat, lng = float(lat), float(lng)
            except (TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                continue
            entries.append({
                "timestamp_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "source": "post_geotag",
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "location_name": loc.get("name"),
                "reference": post.get("shortcode") or post.get("id"),
            })
        entries.sort(key=lambda e: e["timestamp_utc"])
        print(f"[EXIF] Location timeline: {len(entries)} entries")
        return entries

    def export_location_csv(self, timeline: List[Dict],
                            filename: str = "location_timeline.csv",
                            output_dir: str = "~/ig_toolkit/output") -> str:
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp_utc", "source", "latitude", "longitude",
                "location_name", "reference"])
            writer.writeheader()
            writer.writerows(timeline)
        print(f"[EXIF] Timeline CSV exported: {path}")
        return str(path)

    def export_exif_report(self, output_file: str = "exif_report.json",
                           output_dir: str = "~/ig_toolkit/output",
                           posts: Optional[List[Dict]] = None) -> str:
        timeline = self.generate_location_timeline(posts)
        devices = {d.get("device_info", {}).get("Image Model")
                   for d in self.extracted_data
                   if d.get("device_info", {}).get("Image Model")}
        report = {
            "extracted_data": self.extracted_data,
            "location_timeline": timeline,
            "summary": {
                "total_images_processed": len(self.extracted_data),
                "images_with_gps": sum(1 for d in self.extracted_data
                                       if d.get("gps_coordinates")),
                "geotag_entries": sum(1 for e in timeline if e["source"] == "post_geotag"),
                "unique_device_models": sorted(devices),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        path = out / output_file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"[EXIF] Report saved: {path}")
        return str(path)
