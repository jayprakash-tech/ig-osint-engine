"""IG-OSINT-ENGINE Recon Module - Pillar 5: Indirect Reconnaissance.

Passive techniques that work on BOTH public and private profiles:
  1. Private-safe metadata, high-res avatar, bio entity extraction
  2. Reverse image search link generation (Yandex / Lens / Bing / TinEye)
  3. Cross-platform username enumeration (throttled, status-based)
  4. Tagged-post discovery (best-effort) + caption mention scanning
  5. Breach context via optional HIBP API key + local email analysis

All checks are passive reads of publicly served data. Authorized use only.
"""

import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

from .harvester import BASE, HarvestError
from .media_handler import MediaDownloader

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RES = [
    re.compile(r"\+\d{1,3}(?:[\s.-]?\d{1,4}){2,4}\b"),
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
]
URL_RE = re.compile(r"https?://[^\s<>\"']+")
BTC_RES = [
    re.compile(r"\bbc1[a-z0-9]{39,59}\b"),
    re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"),
]
ETH_RE = re.compile(r"\b0x[a-fA-F0-9]{40}\b")
MENTION_RE = re.compile(r"@([a-z0-9._]+)")
HASHTAG_RE = re.compile(r"#(\w+)")
HANDLE_RE = re.compile(r"^[a-z0-9._]{2,30}$")

PLATFORMS = {
    "github": "https://github.com/{u}",
    "gitlab": "https://gitlab.com/{u}",
    "bitbucket": "https://bitbucket.org/{u}",
    "telegram": "https://t.me/{u}",
    "medium": "https://medium.com/@{u}",
    "dev.to": "https://dev.to/{u}",
    "twitch": "https://www.twitch.tv/{u}",
    "pinterest": "https://www.pinterest.com/{u}/",
    "tumblr": "https://{u}.tumblr.com",
    "vk": "https://vk.com/{u}",
    "flickr": "https://www.flickr.com/people/{u}/",
    "soundcloud": "https://soundcloud.com/{u}",
    "steam": "https://steamcommunity.com/id/{u}",
    "youtube": "https://www.youtube.com/@{u}",
    "threads": "https://www.threads.net/@{u}",
    "snapchat": "https://www.snapchat.com/add/{u}",
    "tiktok": "https://www.tiktok.com/@{u}",
    "reddit": "https://www.reddit.com/user/{u}/",
    "linktree": "https://linktr.ee/{u}",
    "about.me": "https://about.me/{u}",
    "gravatar": "https://gravatar.com/{u}",
    "mastodon.social": "https://mastodon.social/@{u}",
    "hub.docker": "https://hub.docker.com/u/{u}",
    "keybase": "https://keybase.io/{u}",
    "disqus": "https://disqus.com/by/{u}/",
}

PRIVATE_TAG_NOTE = ("For private accounts Instagram usually blocks this "
                    "endpoint; empty results are expected, non-empty results "
                    "mean real public tagging exposure.")


# ---------------- 1. Bio entities & avatar ----------------

def extract_bio_entities(bio: str, external_url: Optional[str] = None) -> Dict:
    bio = bio or ""
    phones = []
    for pat in PHONE_RES:
        for m in pat.findall(bio):
            digits = re.sub(r"\D", "", m)
            if 8 <= len(digits) <= 15 and m not in phones:
                phones.append(m)
    urls = URL_RE.findall(bio)
    if external_url:
        urls.insert(0, external_url)
    return {
        "emails": sorted(set(EMAIL_RE.findall(bio))),
        "phones": phones,
        "urls": list(dict.fromkeys(urls)),
        "crypto": {
            "btc_candidates": sorted({m for pat in BTC_RES for m in pat.findall(bio)}),
            "eth_candidates": sorted(set(ETH_RE.findall(bio))),
        },
        "mentions": sorted(set(MENTION_RE.findall(bio.lower()))),
        "hashtags": sorted(set(HASHTAG_RE.findall(bio.lower()))),
    }


def avatar_urls(profile: Dict) -> Dict:
    hd = profile.get("profile_pic_url") or ""
    out = {"hd": hd}
    if hd:
        out["cdn_max_candidate"] = re.sub(r"/s\d+x\d+/", "/s640x640/", hd)
        out["note"] = ("'hd' is the highest resolution Instagram serves via API; "
                       "'cdn_max_candidate' may 404 on some CDNs.")
    return out


def derive_handles(emails: List[str]) -> List[str]:
    handles = set()
    for email in emails:
        local = email.split("@")[0].lower()
        parts = re.split(r"[._\-]+", local)
        candidates = {local, "".join(parts), parts[0] if parts else local}
        for c in candidates:
            if HANDLE_RE.match(c):
                handles.add(c)
    return sorted(handles)


# ---------------- 2. Reverse image search ----------------

def reverse_image_links(image_url: str) -> Dict[str, str]:
    q = quote(image_url, safe="")
    return {
        "yandex": f"https://yandex.com/images/search?rpt=imageview&url={q}",
        "google_lens": f"https://lens.google.com/uploadbyurl?url={q}",
        "bing": f"https://www.bing.com/images/search?q=imgurl:{q}&view=detailv2&iss=sbi",
        "tineye": f"https://tineye.com/search?url={q}",
    }


# ---------------- 3. Username enumeration ----------------

def _check_platform(name: str, url: str, session: requests.Session) -> Dict:
    time.sleep(random.uniform(0.2, 0.9))
    try:
        resp = session.get(url, timeout=12, allow_redirects=True)
        if resp.status_code == 200:
            status = "found"
        elif resp.status_code == 404:
            status = "not_found"
        else:
            status = f"uncertain({resp.status_code})"
    except requests.RequestException:
        status = "error"
    return {"platform": name, "url": url, "status": status}


def enumerate_username(username: str, platforms: Optional[Dict] = None) -> Dict:
    targets = platforms or PLATFORMS
    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "en-US,en;q=0.9",
    })
    jobs = [(name, tpl.format(u=username)) for name, tpl in targets.items()]
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for res in pool.map(lambda j: _check_platform(j[0], j[1], session), jobs):
            results.append(res)
    found = [r for r in results if r["status"] == "found"]
    uncertain = [r for r in results if r["status"].startswith("uncertain")]
    print(f"[RECON] Username @{username}: {len(found)} confirmed footprint(s), "
          f"{len(uncertain)} uncertain")
    return {
        "username": username,
        "checked": len(results),
        "found": found,
        "uncertain": uncertain,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------- 4. Tagged + mentions ----------------

def discover_tagged_posts(harvester, profile: Dict, limit: int = 24) -> Dict:
    uid = profile.get("id")
    if not uid:
        return {"available": False, "reason": "no user id", "posts": []}
    try:
        data = harvester._get_json(
            f"{BASE}/api/v1/usertags/{uid}/",
            params={"count": min(24, limit)})
    except HarvestError as exc:
        return {"available": False, "reason": str(exc),
                "posts": [], "note": PRIVATE_TAG_NOTE}
    posts = []
    for item in data.get("items") or []:
        posts.append({
            "shortcode": item.get("code"),
            "timestamp": item.get("taken_at"),
            "owner": (item.get("user") or {}).get("username"),
            "caption_snippet": (((item.get("caption") or {}).get("text")) or "")[:80],
            "location": (item.get("location") or {}).get("name"),
        })
    return {"available": True, "count": len(posts), "posts": posts,
            "note": PRIVATE_TAG_NOTE}


def scan_caption_mentions(posts: List[Dict], username: str) -> List[Dict]:
    needle = f"@{username.lower()}"
    hits = []
    for post in posts:
        cap = (post.get("caption") or "").lower()
        if needle in cap:
            hits.append({
                "shortcode": post.get("shortcode"),
                "timestamp": post.get("timestamp"),
                "caption_snippet": (post.get("caption") or "")[:80],
            })
    return hits


# ---------------- 5. Breach context ----------------

def check_breach_context(emails: List[str],
                         hibp_api_key: Optional[str] = None) -> Dict:
    key = hibp_api_key or os.environ.get("HIBP_API_KEY")
    out = {}
    for email in emails:
        entry = {"email": email, "breaches": None, "status": "not_checked"}
        if not key:
            entry["status"] = "no_api_key"
            entry["hint"] = ("Set HIBP_API_KEY or pass --hibp-key to query "
                             "breaches (HIBP v3 is a paid API).")
            out[email] = entry
            continue
        try:
            resp = requests.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(email)}",
                headers={"hibp-api-key": key,
                         "user-agent": "ig-osint-engine-research"},
                params={"truncateResponse": "false"}, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                entry["status"] = "breached"
                entry["breaches"] = [{
                    "name": b.get("Name"),
                    "date": b.get("BreachDate"),
                    "data_classes": b.get("DataClasses", []),
                } for b in data]
            elif resp.status_code == 404:
                entry["status"] = "no_breaches_found"
            elif resp.status_code == 401:
                entry["status"] = "invalid_api_key"
            else:
                entry["status"] = f"http_{resp.status_code}"
        except requests.RequestException as exc:
            entry["status"] = f"error: {exc}"
        out[email] = entry
    return out


# ---------------- orchestrator ----------------

def run_full_recon(harvester, username: str, out_dir: str,
                   hibp_api_key: Optional[str] = None,
                   check_platforms: bool = True,
                   download_avatar: bool = True,
                   posts: Optional[List[Dict]] = None) -> Dict:
    profile = harvester.fetch_user_profile(username)
    entities = extract_bio_entities(profile.get("biography", ""),
                                    profile.get("external_url"))
    avatars = avatar_urls(profile)

    avatar_path = None
    if download_avatar and avatars.get("hd"):
        dl = MediaDownloader(str(harvester.base_dir))
        avatar_path = dl.download_media(
            avatars["hd"], f"{username}_avatar.jpg", username)

    report = {
        "username": username,
        "is_private": profile.get("is_private"),
        "profile_snapshot": {
            "full_name": profile.get("full_name"),
            "biography": profile.get("biography"),
            "external_url": profile.get("external_url"),
            "followers_count": profile.get("followers_count"),
            "following_count": profile.get("following_count"),
            "posts_count": profile.get("posts_count"),
        },
        "bio_entities": entities,
        "derived_handles": derive_handles(entities["emails"]),
        "avatar": {"urls": avatars, "local_path": avatar_path},
        "reverse_image_links": reverse_image_links(avatars.get("hd", "")),
        "cross_platform": enumerate_username(username) if check_platforms else None,
        "tagged_posts": discover_tagged_posts(harvester, profile),
        "caption_mentions_in_harvested_posts": scan_caption_mentions(
            posts or [], username),
        "breach_context": check_breach_context(entities["emails"], hibp_api_key),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{username}_recon_report.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"[RECON] Private: {report['is_private']} | "
          f"emails {len(entities['emails'])} | phones {len(entities['phones'])} | "
          f"crypto {len(entities['crypto']['btc_candidates']) + len(entities['crypto']['eth_candidates'])}")
    if report["cross_platform"]:
        for hit in report["cross_platform"]["found"]:
            print(f"  [FOUND] {hit['platform']}: {hit['url']}")
    print(f"[RECON] Report saved: {path}")
    return report
