"""Instagram Monitor Module - Pillar 4: differential change detection.

Compares the current profile/post state against the latest saved snapshot
and flags bio edits, username changes, privacy shifts, follower spikes,
and possibly-deleted posts. Offline comparison logic; fetching is done
by the harvester.
"""

import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional


class ChangeDetector:
    """Snapshot diffing engine with a cumulative post registry."""

    def __init__(self, base_dir: str = "~/ig_toolkit",
                 follower_spike_threshold: float = 0.1):
        self.base_dir = Path(base_dir).expanduser()
        self.monitor_dir = self.base_dir / "data" / "monitoring"
        self.monitor_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.base_dir / "output"
        self.follower_spike_threshold = follower_spike_threshold

    # ---------------- state persistence ----------------

    def _state_files(self, username: str) -> List[Path]:
        return sorted(self.monitor_dir.glob(f"{username}_state_*.json"))

    def get_latest_state(self, username: str) -> Optional[Dict]:
        files = self._state_files(username)
        if not files:
            return None
        try:
            with open(files[-1], "r", encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            return None

    def save_state(self, username: str, profile: Dict, posts: List[Dict]) -> str:
        now_iso = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        prev = self.get_latest_state(username)
        registry: Dict = dict(prev.get("post_registry", {})) if prev else {}

        current_ids, timestamps = [], []
        for post in posts:
            pid = str(post.get("id") or "")
            if not pid:
                continue
            current_ids.append(pid)
            ts = post.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamps.append(ts)
            meta = registry.get(pid, {})
            registry[pid] = {
                "shortcode": post.get("shortcode"),
                "timestamp": ts,
                "caption_snippet": (post.get("caption") or "")[:80],
                "first_seen": meta.get("first_seen", now_iso),
                "last_seen": now_iso,
            }

        state = {
            "username": username,
            "saved_at": now_iso,
            "profile": profile,
            "current_post_ids": current_ids,
            "post_registry": registry,
            "window_oldest_timestamp": min(timestamps) if timestamps else None,
        }
        filepath = self.monitor_dir / f"{username}_state_{stamp}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        print(f"[MONITOR] State saved: {filepath.name}")
        return str(filepath)

    # ---------------- diffing ----------------

    def detect_changes(self, username: str, profile: Dict,
                       posts: List[Dict]) -> Dict:
        latest = self.get_latest_state(username)
        if latest is None:
            self.save_state(username, profile, posts)
            print("[MONITOR] No previous state - initial snapshot saved.")
            return {"status": "initial_state_saved", "username": username,
                    "changes_detected": [],
                    "summary": {"total_changes": 0, "severity": "none"}}

        changes: List[Dict] = []
        prev_profile = latest.get("profile", {})
        changes += self._profile_changes(prev_profile, profile)
        changes += self._count_changes(prev_profile, profile)
        changes += self._post_changes(latest, posts, profile)

        self.save_state(username, profile, posts)
        severity = self._severity(changes)
        result = {
            "status": "compared",
            "username": username,
            "comparison_timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_timestamp": latest.get("saved_at"),
            "changes_detected": changes,
            "summary": {
                "total_changes": len(changes),
                "severity": severity,
                "profile_changes": sum(1 for c in changes if c["type"] == "profile"),
                "post_changes": sum(1 for c in changes if c["type"] == "posts"),
                "count_changes": sum(1 for c in changes if c["type"] == "counts"),
            },
        }
        if changes:
            print(f"[MONITOR] {len(changes)} change(s) detected "
                  f"(severity: {severity}):")
            for c in changes:
                print(f"  - [{c['severity']}] {c['description']}")
        else:
            print("[MONITOR] No changes detected.")
        return result

    def _profile_changes(self, prev: Dict, curr: Dict) -> List[Dict]:
        changes = []
        if prev.get("username") and curr.get("username") \
                and prev["username"] != curr["username"]:
            changes.append({"type": "profile", "field": "username",
                            "severity": "high",
                            "previous_value": prev["username"],
                            "current_value": curr["username"],
                            "description": f"Username renamed: "
                                           f"{prev['username']} -> {curr['username']}"})
        pb = prev.get("biography") or ""
        cb = curr.get("biography") or ""
        if pb != cb:
            ratio = SequenceMatcher(None, pb, cb).ratio()
            sev = "high" if ratio < 0.5 else "medium" if ratio < 0.9 else "low"
            changes.append({"type": "profile", "field": "biography",
                            "severity": sev, "previous_value": pb,
                            "current_value": cb,
                            "similarity_score": round(ratio, 3),
                            "description": f"Bio changed (similarity {ratio:.0%})"})
        if (prev.get("full_name") or "") != (curr.get("full_name") or ""):
            changes.append({"type": "profile", "field": "full_name",
                            "severity": "medium",
                            "previous_value": prev.get("full_name"),
                            "current_value": curr.get("full_name"),
                            "description": "Display name changed"})
        if (prev.get("external_url") or "") != (curr.get("external_url") or ""):
            changes.append({"type": "profile", "field": "external_url",
                            "severity": "medium",
                            "previous_value": prev.get("external_url") or "None",
                            "current_value": curr.get("external_url") or "None",
                            "description": "External URL changed"})
        if prev.get("profile_pic_url") and curr.get("profile_pic_url") \
                and prev["profile_pic_url"] != curr["profile_pic_url"]:
            changes.append({"type": "profile", "field": "profile_picture",
                            "severity": "medium",
                            "description": "Profile picture changed"})
        if bool(prev.get("is_private")) != bool(curr.get("is_private")):
            changes.append({"type": "profile", "field": "privacy_status",
                            "severity": "high",
                            "description": f"Privacy changed: "
                                           f"{'Private' if prev.get('is_private') else 'Public'}"
                                           f" -> "
                                           f"{'Private' if curr.get('is_private') else 'Public'}"})
        if bool(prev.get("is_verified")) != bool(curr.get("is_verified")):
            changes.append({"type": "profile", "field": "verification_status",
                            "severity": "high",
                            "description": "Verification status changed"})
        return changes

    def _count_changes(self, prev: Dict, curr: Dict) -> List[Dict]:
        changes = []
        for field, label in (("followers_count", "Followers"),
                             ("following_count", "Following")):
            p = int(prev.get(field) or 0)
            c = int(curr.get(field) or 0)
            if p <= 0 or c == p:
                continue
            delta = c - p
            pct = abs(delta) / p
            if pct >= self.follower_spike_threshold:
                sev = "high" if pct > 0.25 else "medium"
                direction = "gained" if delta > 0 else "lost"
                changes.append({"type": "counts", "field": field,
                                "severity": sev, "previous_count": p,
                                "current_count": c, "change_amount": delta,
                                "change_percentage": round(pct * 100, 2),
                                "description": f"{label} {direction} "
                                               f"{abs(delta):,} ({pct:.1%})"})
        return changes

    def _post_changes(self, latest: Dict, posts: List[Dict],
                      profile: Dict) -> List[Dict]:
        changes = []
        current_ids = {str(p.get("id")) for p in posts if p.get("id")}
        registry = latest.get("post_registry", {})

        new_ids = [pid for pid in current_ids if pid not in registry]
        if new_ids:
            new_set = set(new_ids)
            new_posts = [{"id": str(p.get("id")), "shortcode": p.get("shortcode"),
                          "caption_snippet": (p.get("caption") or "")[:80]}
                         for p in posts if str(p.get("id")) in new_set]
            changes.append({"type": "posts", "field": "new_posts",
                            "severity": "low", "new_count": len(new_ids),
                            "new_posts": new_posts[:10],
                            "description": f"{len(new_ids)} new post(s)"})

        # Only flag deletion for posts that SHOULD still be inside the
        # current fetch window - avoids false positives from pagination.
        timestamps = [p.get("timestamp") for p in posts
                      if isinstance(p.get("timestamp"), (int, float))]
        window_oldest = min(timestamps) if timestamps else None
        possibly_deleted = []
        if window_oldest is not None:
            for pid, meta in registry.items():
                if pid in current_ids:
                    continue
                ts = meta.get("timestamp")
                if isinstance(ts, (int, float)) and ts >= window_oldest:
                    possibly_deleted.append({
                        "id": pid, "shortcode": meta.get("shortcode"),
                        "caption_snippet": meta.get("caption_snippet"),
                        "timestamp": ts})
        if possibly_deleted:
            changes.append({"type": "posts", "field": "possibly_deleted_posts",
                            "severity": "high",
                            "deleted_count": len(possibly_deleted),
                            "deleted_posts": possibly_deleted[:10],
                            "description": f"{len(possibly_deleted)} post(s) "
                                           f"possibly deleted/archived"})

        p_count = int(latest.get("profile", {}).get("posts_count") or 0)
        c_count = int(profile.get("posts_count") or 0)
        if p_count > 0 and c_count < p_count:
            changes.append({"type": "posts", "field": "posts_count_drop",
                            "severity": "high", "previous_count": p_count,
                            "current_count": c_count,
                            "description": f"Total post count dropped "
                                           f"{p_count} -> {c_count}"})
        return changes

    @staticmethod
    def _severity(changes: List[Dict]) -> str:
        if not changes:
            return "none"
        levels = {c.get("severity", "low") for c in changes}
        if "high" in levels:
            return "high"
        if "medium" in levels:
            return "medium"
        return "low"

    # ---------------- reporting ----------------

    def generate_monitoring_report(self, username: str,
                                   output_file: Optional[str] = None) -> str:
        files = self._state_files(username)
        if not files:
            return "No monitoring data found"
        timeline = []
        prev = None
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (ValueError, OSError):
                continue
            if prev is not None:
                pf, cf = prev.get("profile", {}), state.get("profile", {})
                entry = []
                if pf.get("followers_count") != cf.get("followers_count"):
                    entry.append(f"Followers {pf.get('followers_count')} -> "
                                 f"{cf.get('followers_count')}")
                if (pf.get("biography") or "") != (cf.get("biography") or ""):
                    entry.append("Bio changed")
                pr = len(prev.get("post_registry", {}))
                cr = len(state.get("post_registry", {}))
                if cr > pr:
                    entry.append(f"{cr - pr} new post(s) seen")
                if int(pf.get("posts_count") or 0) > int(cf.get("posts_count") or 0):
                    entry.append("Post count dropped")
                if entry:
                    timeline.append({"timestamp": state.get("saved_at"),
                                     "changes": entry})
            prev = state

        report = {"username": username, "total_snapshots": len(files),
                  "change_timeline": timeline,
                  "generated_at": datetime.now(timezone.utc).isoformat()}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if output_file is None:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_file = f"{username}_monitoring_report_{stamp}.json"
        path = self.output_dir / output_file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"[MONITOR] Report saved: {path}")
        return str(path)

    def setup_continuous_monitoring(self, username: str, interval_hours: int = 1):
        print(f"[MONITOR] Continuous monitoring for @{username} "
              f"every {interval_hours}h.")
        print("[MONITOR] Linux/Kali cron (crontab -e):")
        minute = 0 if interval_hours == 1 else 0
        hours = "*" if interval_hours == 1 else f"*/{interval_hours}"
        print(f"  {minute} {hours} * * * cd ~/ig_toolkit && "
              f"./venv/bin/python main.py monitor --username {username} "
              f"--check >> ~/ig_toolkit/monitor.log 2>&1")
        print("[MONITOR] Termux: install cronie (pkg install cronie) then "
              "run 'crond', or use termux-job-scheduler for periodic runs.")
