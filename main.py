#!/usr/bin/env python3
"""IG-OSINT-ENGINE - CLI entry point (v1.1 with Pillar 5 Recon)."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.harvester import HarvestError, InstagramHarvester
from modules.analyzer import GraphAnalyzer, TemporalProfiler
from modules.media_handler import EXIFExtractor, MediaDownloader
from modules.monitor import ChangeDetector
from modules.recon import run_full_recon
BANNER = r"""
██╗  ██████╗     ██████╗ ███████╗██╗███╗   ██╗████████╗
██║ ██╔════╝     ██╔═══██╗██╔════╝██║████╗  ██║╚══██╔══╝
██║ ██║  ███╗    ██║   ██║███████╗██║██╔██╗ ██║   ██║
██║ ██║   ██║    ██║   ██║╚════██║██║██║╚██╗██║   ██║
██║ ╚██████╔╝    ╚██████╔╝███████║██║██║ ╚████║   ██║
╚═╝  ╚═════╝      ╚═════╝ ╚══════╝╚═╝╚═╝  ╚═══╝   ╚═╝
        ███████╗███╗   ██╗ ██████╗ ██╗███╗   ██╗███████╗
        ██╔════╝████╗  ██║██╔════╝ ██║████╗  ██║██╔════╝
        █████╗  ██╔██╗ ██║██║  ███╗██║██╔██╗ ██║█████╗
        ██╔══╝  ██║╚██╗██║██║   ██║██║██║╚██╗██║██╔══╝
        ███████╗██║ ╚████║╚██████╔╝██║██║ ╚████║███████╗
        ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝╚══════╝
"""

def print_banner():
    cyan, mag, dim, reset = "\033[96m", "\033[95m", "\033[2m", "\033[0m"
    print(cyan + BANNER + reset)
    print(mag + "  Modular Instagram Intelligence Framework   v1.1.0" + reset)
    print(dim + "  Pillars: Graph | Temporal | GeoOSINT | Monitor | Recon")
    print(f"  Session start: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("  Ethical use only: public data + authorized research." + reset)

def setup_argument_parser():
    parser = argparse.ArgumentParser(prog="ig-osint-engine", description="Modular Instagram OSINT engine.")
    parser.add_argument("--version", action="version", version="ig-osint-engine 1.1.0")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--cookies", default=None)

    sub = parser.add_subparsers(dest="command")

    # Harvest
    p = sub.add_parser("harvest")
    p.add_argument("--username", required=True)
    p.add_argument("--posts", type=int, default=50)
    p.add_argument("--followers", type=int, default=100)
    p.add_argument("--following", type=int, default=100)
    p.add_argument("--profile-only", action="store_true")

    # Analyze
    p = sub.add_parser("analyze")
    p.add_argument("--username", required=True)
    p.add_argument("--graph", action="store_true")
    p.add_argument("--communities", action="store_true")
    p.add_argument("--influential", type=int, default=0)
    p.add_argument("--temporal", action="store_true")
    p.add_argument("--mutual", nargs=2, metavar=("USER1", "USER2"))

    # Media
    p = sub.add_parser("media")
    p.add_argument("--username", required=True)
    p.add_argument("--download", action="store_true")
    p.add_argument("--exif", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--location-timeline", action="store_true")

    # Monitor
    p = sub.add_parser("monitor")
    p.add_argument("--username", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--setup-continuous", action="store_true")
    p.add_argument("--interval", type=int, default=1)

    # Compare
    p = sub.add_parser("compare")
    p.add_argument("--username1", required=True)
    p.add_argument("--username2", required=True)
    p.add_argument("--mutual-followers", action="store_true")

    # Recon (Pillar 5)
    p = sub.add_parser("recon", help="Indirect recon (avatars, cross-platform, bio entities)")
    p.add_argument("--username", required=True)
    p.add_argument("--hibp-key", default=None, help="Optional HaveIBeenPwned API key")
    p.add_argument("--skip-platforms", action="store_true")

    return parser

def _snap_list(harvester, username, dtype):
    snap = harvester.get_latest_snapshot(username, dtype)
    if not snap: return None
    data = snap.get("data")
    return data if isinstance(data, list) else None

def cmd_harvest(args):
    h = InstagramHarvester(str(args.base_path))
    if args.cookies: h.load_session_cookies(args.cookies)
    profile = h.fetch_user_profile(args.username)
    if not args.profile_only:
        h.fetch_user_posts(args.username, args.posts)
        h.fetch_followers(args.username, args.followers)
        h.fetch_following(args.username, args.following)
    print(f"[MAIN] @{profile.get('username')} | followers {profile.get('followers_count')} | posts {profile.get('posts_count')}")

def cmd_analyze(args):
    h = InstagramHarvester(str(args.base_path))
    out = str(args.out_path)
    if args.graph or args.communities or args.influential:
        followers = _snap_list(h, args.username, "followers")
        following = _snap_list(h, args.username, "following")
        if followers and following:
            ga = GraphAnalyzer()
            ga.build_network_from_followers(args.username, followers, following)
            ga.export_graphml(f"{args.username}_network.graphml", out)
    if args.temporal:
        posts = _snap_list(h, args.username, "posts")
        if posts:
            tp = TemporalProfiler()
            tp.load_posts_data(posts)
            hm = tp.generate_activity_heatmap()
            print(f"[MAIN] Peak: {hm['peak_activity']['day']} {hm['peak_activity']['hour_utc']} UTC")
            tp.generate_temporal_report(f"{args.username}_temporal_report.json", out)

def cmd_media(args):
    h = InstagramHarvester(str(args.base_path))
    posts = _snap_list(h, args.username, "posts")
    if not posts: return
    dl = MediaDownloader(str(args.base_path))
    if args.download: dl.batch_download_posts(posts[:args.limit], args.username)
    if args.exif:
        user_dir = dl.media_dir / MediaDownloader._safe_name(args.username)
        files = sorted(user_dir.glob("*.jpg")) + sorted(user_dir.glob("*.jpeg"))
        if files:
            ex = EXIFExtractor()
            ex.batch_extract_exif([str(p) for p in files])
            ex.export_exif_report(f"{args.username}_exif_report.json", str(args.out_path), posts=posts)

def cmd_monitor(args):
    det = ChangeDetector(str(args.base_path))
    if args.check:
        h = InstagramHarvester(str(args.base_path))
        if args.cookies: h.load_session_cookies(args.cookies)
        profile = h.fetch_user_profile(args.username)
        posts = h.fetch_user_posts(args.username, 30)
        det.detect_changes(args.username, profile, posts)
    if args.report: det.generate_monitoring_report(args.username)

def cmd_compare(args):
    h = InstagramHarvester(str(args.base_path))
    if args.mutual_followers:
        f1 = _snap_list(h, args.username1, "followers")
        f2 = _snap_list(h, args.username2, "followers")
        if f1 and f2:
            ga = GraphAnalyzer()
            r = ga.find_mutual_connections(args.username1, args.username2, f1, f2)
            print(f"[MAIN] Mutual followers: {r['mutual_count']} | Jaccard: {r['jaccard_similarity']}")

def cmd_recon(args):
    h = InstagramHarvester(str(args.base_path))
    if args.cookies: h.load_session_cookies(args.cookies)
    posts = _snap_list(h, args.username, "posts")
    run_full_recon(h, args.username, str(args.out_path),
                   hibp_api_key=args.hibp_key,
                   check_platforms=not args.skip_platforms,
                   posts=posts or [])

def main():
    parser = setup_argument_parser()
    args = parser.parse_args()
    if not args.command: parser.print_help(); return

    base = Path(args.base_dir).expanduser() if args.base_dir else Path(__file__).resolve().parent
    args.base_path = base
    args.out_path = Path(args.output_dir).expanduser() if args.output_dir else base / "output"
    args.out_path.mkdir(parents=True, exist_ok=True)

    print_banner()
    handlers = {"harvest": cmd_harvest, "analyze": cmd_analyze, "media": cmd_media, 
                "monitor": cmd_monitor, "compare": cmd_compare, "recon": cmd_recon}
    try:
        handlers[args.command](args)
    except KeyboardInterrupt: print("\n[MAIN] Cancelled.")
    except (HarvestError, ValueError) as exc: print(f"[MAIN] Error: {exc}"); sys.exit(1)
    except Exception as exc:
        if args.verbose: raise
        print(f"[MAIN] Unexpected error: {exc} (use --verbose for traceback)"); sys.exit(1)

if __name__ == "__main__":
    main()
