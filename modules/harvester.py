"""Instagram Harvester Module - data extraction with rate-limit defense.

Collects PUBLIC profile data only, using your own logged-in session cookies.
Use responsibly: authorized research, Instagram ToS, and local laws apply.
"""

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

IG_APP_ID = "936619743392459"
BASE = "https://www.instagram.com"


class HarvestError(Exception):
    """Raised when harvesting fails for a non-retryable reason."""


class InstagramHarvester:
    """Instagram data harvester with throttling, backoff, and session support."""

    def __init__(self, base_dir: str = "~/ig_toolkit"):
        self.base_dir = Path(base_dir).expanduser()
        self.data_dir = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.min_delay = 3.0
        self.max_delay = 9.0
        self.backoff_factor = 2.0
        self.max_retries = 5
        self.timeout = 30

        self.session = requests.Session()
        self._setup_session()
        self._user_id_cache: Dict[str, str] = {}

    # ---------------- session management ----------------

    def _setup_session(self):
        self.session.headers.update({
            "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "X-IG-App-ID": IG_APP_ID,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + "/",
            "Origin": BASE,
            "Connection": "keep-alive",
        })

    def load_session_cookies(self, cookie_file: str) -> bool:
        """Load cookies from a JSON dict or a browser-export list."""
        path = Path(cookie_file).expanduser()
        if not path.exists():
            print(f"[HARVESTER] Cookie file not found: {path}")
            return False
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        cookies: Dict[str, str] = {}
        if isinstance(raw, dict):
            cookies = {str(k): str(v) for k, v in raw.items()}
        elif isinstance(raw, list):
            for c in raw:
                if isinstance(c, dict) and "name" in c and "value" in c:
                    cookies[str(c["name"])] = str(c["value"])

        if not cookies:
            print("[HARVESTER] No usable cookies found in file.")
            return False

        self.session.cookies.update(cookies)
        if cookies.get("csrftoken"):
            self.session.headers["X-CSRFToken"] = cookies["csrftoken"]
        print(f"[HARVESTER] Loaded {len(cookies)} session cookies.")
        if "sessionid" not in cookies:
            print("[HARVESTER] WARNING: no 'sessionid' cookie - most endpoints will fail.")
        return True

    def save_session_cookies(self, cookie_file: str):
        path = Path(cookie_file).expanduser()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.session.cookies.get_dict(), f, indent=2)
        print(f"[HARVESTER] Cookies saved to {path}")

    # ---------------- rate-limit defense ----------------

    def _human_delay(self):
        delay = random.uniform(self.min_delay, self.max_delay)
        delay = max(1.0, delay + random.uniform(-0.5, 0.5))
        time.sleep(delay)

    def _backoff(self, attempt: int, retry_after: Optional[str] = None):
        wait = None
        if retry_after:
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                wait = None
        if wait is None:
            wait = min(5.0 * (self.backoff_factor ** attempt), 300.0)
        wait = min(wait * random.uniform(0.8, 1.2), 600.0)
        print(f"[HARVESTER] Backing off {wait:.1f}s (attempt {attempt + 1})")
        time.sleep(wait)

    def _get_json(self, url: str, params: Optional[Dict] = None) -> Dict:
        last_error = "unknown error"
        for attempt in range(self.max_retries):
            self._human_delay()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = str(exc)
                self._backoff(attempt)
                continue

            if resp.status_code == 429:
                last_error = "429 rate limited"
                self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            if resp.status_code in (401, 403):
                raise HarvestError(
                    f"{resp.status_code} from Instagram. Session cookies are "
                    "missing/expired or access is restricted. Load fresh cookies."
                )
            if resp.status_code == 404:
                raise HarvestError(f"404 Not Found (username may not exist): {url}")
            if resp.status_code >= 500:
                last_error = f"server error {resp.status_code}"
                self._backoff(attempt)
                continue
            if resp.status_code != 200:
                raise HarvestError(f"Unexpected status {resp.status_code} for {url}")

            try:
                return resp.json()
            except ValueError:
                raise HarvestError(
                    "Instagram returned a non-JSON page (login/checkpoint). "
                    "Load valid session cookies."
                )

        raise HarvestError(f"Failed after {self.max_retries} attempts: {last_error}")

    # ---------------- helpers ----------------

    @staticmethod
    def _clean_username(username: str) -> str:
        username = username.strip().lstrip("@").lower()
        if not re.fullmatch(r"[a-z0-9._]{1,30}", username):
            raise HarvestError(f"Invalid username: {username!r}")
        return username

    def _resolve_user_id(self, username: str) -> str:
        username = self._clean_username(username)
        if username in self._user_id_cache:
            return self._user_id_cache[username]
        profile = self.fetch_user_profile(username)
        uid = profile.get("id")
        if not uid:
            raise HarvestError(f"Could not resolve user id for @{username}")
        return uid

    # ---------------- public API ----------------

    def fetch_user_profile(self, username: str) -> Dict:
        username = self._clean_username(username)
        data = self._get_json(
            f"{BASE}/api/v1/users/web_profile_info/",
            params={"username": username},
        )
        user = (data.get("data") or {}).get("user")
        if not user:
            raise HarvestError(f"No profile data returned for @{username}")
        if user.get("id"):
            self._user_id_cache[username] = str(user["id"])

        profile = {
            "id": str(user.get("id") or ""),
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "biography": user.get("biography", ""),
            "external_url": user.get("external_url"),
            "is_private": user.get("is_private", False),
            "is_verified": user.get("is_verified", False),
            "followers_count": (user.get("edge_followed_by") or {}).get("count", 0),
            "following_count": (user.get("edge_follow") or {}).get("count", 0),
            "posts_count": (user.get("edge_owner_to_timeline_media") or {}).get("count", 0),
            "profile_pic_url": user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
        }
        self._save_snapshot(username, "profile", profile)
        print(f"[HARVESTER] Profile fetched for @{username}")
        return profile

    def fetch_user_posts(self, username: str, limit: int = 50) -> List[Dict]:
        username = self._clean_username(username)
        user_id = self._resolve_user_id(username)
        posts: List[Dict] = []
        seen_ids = set()
        max_id = None
        print(f"[HARVESTER] Fetching up to {limit} posts for @{username}")

        while len(posts) < limit:
            params = {"count": min(12, limit - len(posts))}
            if max_id:
                params["max_id"] = max_id
            data = self._get_json(f"{BASE}/api/v1/feed/user/{user_id}/", params=params)
            items = data.get("items") or []
            if not items:
                break
            for item in items:
                pid = str(item.get("pk") or item.get("id") or "")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                posts.append(self._normalize_post(item))
                if len(posts) >= limit:
                    break
            if not data.get("more_available"):
                break
            max_id = data.get("next_max_id")
            if not max_id:
                break

        self._save_snapshot(username, "posts", posts)
        print(f"[HARVESTER] Total posts fetched: {len(posts)}")
        return posts

    @staticmethod
    def _normalize_post(item: Dict) -> Dict:
        caption_obj = item.get("caption") or {}
        caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""
        candidates = ((item.get("image_versions2") or {}).get("candidates")) or []
        best = max(candidates, key=lambda c: c.get("width", 0)) if candidates else {}
        videos = item.get("video_versions") or []
        loc = item.get("location") or {}
        location = None
        if isinstance(loc, dict) and (loc.get("lat") or loc.get("lng") or loc.get("name")):
            location = {
                "name": loc.get("name"),
                "address": loc.get("address"),
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "pk": loc.get("pk"),
            }
        return {
            "id": str(item.get("pk") or item.get("id") or ""),
            "shortcode": item.get("code", ""),
            "caption": caption,
            "timestamp": item.get("taken_at"),
            "like_count": item.get("like_count", 0),
            "comment_count": item.get("comment_count", 0),
            "is_video": bool(videos) or item.get("media_type") == 2,
            "display_url": best.get("url"),
            "video_url": videos[0].get("url") if videos else None,
            "width": best.get("width"),
            "height": best.get("height"),
            "location": location,
        }

    def fetch_followers(self, username: str, limit: int = 100) -> List[Dict]:
        return self._fetch_connections(username, "followers", limit)

    def fetch_following(self, username: str, limit: int = 100) -> List[Dict]:
        return self._fetch_connections(username, "following", limit)

    def _fetch_connections(self, username: str, kind: str, limit: int) -> List[Dict]:
        username = self._clean_username(username)
        user_id = self._resolve_user_id(username)
        results: List[Dict] = []
        seen = set()
        max_id = None
        print(f"[HARVESTER] Fetching up to {limit} {kind} for @{username}")

        while len(results) < limit:
            params = {
                "count": min(50, limit - len(results)),
                "search_surface": "follow_list_page",
            }
            if max_id:
                params["max_id"] = max_id
            try:
                data = self._get_json(
                    f"{BASE}/api/v1/friendships/{user_id}/{kind}/", params=params
                )
            except HarvestError as exc:
                if results:
                    print(f"[HARVESTER] Partial result saved ({len(results)}): {exc}")
                    break
                raise
            users = data.get("users") or []
            if not users:
                break
            for u in users:
                uname = u.get("username")
                if not uname or uname in seen:
                    continue
                seen.add(uname)
                results.append({
                    "username": uname,
                    "full_name": u.get("full_name", ""),
                    "is_verified": u.get("is_verified", False),
                    "is_private": u.get("is_private", False),
                    "id": str(u.get("pk") or ""),
                })
                if len(results) >= limit:
                    break
            max_id = data.get("next_max_id")
            if not max_id:
                break

        self._save_snapshot(username, kind, results)
        print(f"[HARVESTER] Total {kind} fetched: {len(results)}")
        if not results:
            print("[HARVESTER] NOTE: Instagram heavily restricts follower lists. "
                  "Empty results usually mean restriction, not zero followers.")
        return results

    # ---------------- snapshots ----------------

    def _save_snapshot(self, username: str, data_type: str, data) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{username}_{data_type}_{timestamp}.json"
        filepath = self.data_dir / filename
        payload = {
            "username": username,
            "data_type": data_type,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        print(f"[HARVESTER] Snapshot saved: {filename}")
        return str(filepath)

    def get_latest_snapshot(self, username: str, data_type: str) -> Optional[Dict]:
        username = self._clean_username(username)
        files = sorted(self.data_dir.glob(f"{username}_{data_type}_*.json"))
        if not files:
            return None
        with open(files[-1], "r", encoding="utf-8") as f:
            return json.load(f)
