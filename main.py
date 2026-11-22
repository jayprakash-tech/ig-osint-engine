#!/usr/bin/env python3
"""IG-OSINT-ENGINE - CLI entry point.

Wires the harvester, analyzer, media handler, and monitor modules into a
single command-line intelligence engine. Public data + your own session
cookies only. Authorized research use.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules.harvester import HarvestError, InstagramHarvester
from modules.analyzer import GraphAnalyzer, TemporalProfiler
from modules.media_handler import EXIFExtractor, MediaDownloader
from modules.monitor import ChangeDetector

SEVERITY_ICON = {"high": "[HIGH]", "medium": "[MED ]", "low": "[LOW ]"}


def setup_argument_parser():
    parser = argparse.ArgumentParser(
        prog="ig-osint-engine",
        description="Modular Instagram OSINT intelligence engine.",
    )
    parser.add_argument("--version", action="version", version="ig-osint-engine 1.0.0")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print full tracebacks on error")
    parser.add_argument("--base-dir", default=None,
                        help="Toolkit root (default: folder containing main.py)")
    parser.add_argument("--output-dir", default=None,
                        help="Reports/exports dir (default: <base>/output)")
    parser.add_argument("--cookies", default=None,
                        help="Path to your session cookies JSON")

    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("harvest", help="Collect profile, posts, followers")
    p.add_argument("--username", required=True)
    p.add_argument("--posts", type=int, default=50)
    p.add_argument("--followers", type=int, default=100)
    p.add_argument("--following", type=int, default=100)
    p.add_argument("--profile-only", action="store_true")

    p = sub.add_parser("analyze", help="Graph + temporal analysis")
    p.add_argument("--username", required=True)
    p.add_argument("--graph", action="store_true")
    p.add_argument("--communities", action="store_true")
    p.add_argument("--influential", type=int, default=0)
    p.add_argument("--temporal", action="store_true")
    p.add_argument("--mutual", nargs=2, metavar=("USER1", "USER2"))

    p = sub.add_parser("media", help="Download media + EXIF/geotag intel")
    p.add_argument("--username", required=True)
    p.add_argument("--download", action="store_true")
    p.add_argument("--exif", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--location-timeline", action="store_true")

    p = sub.add_parser("monitor", help="Change detection")
    p.add_argument("--username", required=True)
    p.add_argument("--check", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--setup-continuous", action="store_true")
    p.add_argument("--interval", type=int, default=1)

    p = sub.add_parser("compare", help="Compare two accounts")
    p.add_argument("--username1", required=True)
    p.add_argument("--username2", required=True)
    p.add_argument("--mutual-followers", action="store_true")
    p.add_argument("--network-comparison", action="store_true")

    return parser


def _snap_list(harvester, username, dtype):
    snap = harvester.get_latest_snapshot(username, dtype)
    if not snap:
        return None
    data = snap.get("data")
    return data if isinstance(data, list) else None


def cmd_harvest(args):
    h = InstagramHarvester(str(args.base_path))
    if args.cookies:
        h.load_session_cookies(args.cookies)
    profile = h.fetch_user_profile(args.username)
    if not args.profile_only:
        h.fetch_user_posts(args.username, args.posts)
        h.fetch_followers(args.username, args.followers)
        h.fetch_following(args.username, args.following)
    print(f"[MAIN] @{profile.get('username')} | "
          f"followers {profile.get('followers_count')} | "
          f"following {profile.get('following_count')} | "
          f"posts {profile.get('posts_count')} | "
          f"private {profile.get('is_private')} | "
          f"verified {profile.get('is_verified')}")
    print("[MAIN] Harvest complete.")


def cmd_analyze(args):
    h = InstagramHarvester(str(args.base_path))
    out = str(args.out_path)

    if args.graph or args.communities or args.influential:
        followers = _snap_list(h, args.username, "followers")
        following = _snap_list(h, args.username, "following")
        if followers is None or following is None:
            print("[MAIN] No follower/following snapshots. Run harvest first.")
        else:
            ga = GraphAnalyzer()
            ga.build_network_from_followers(args.username, followers, following)
            ga.export_graphml(f"{args.username}_network.graphml", out)
            if args.communities:
                comm = ga.detect_communities()
                print(f"[MAIN] Communities: {comm['num_communities']} "
                      f"(modularity {comm['modularity']})")
            if args.influential > 0:
                for node in ga.find_influential_nodes(args.influential)[:10]:
                    print(f"  @{node['username']} score={node['combined_score']} "
                          f"type={node['node_type']}")
            stats = ga.get_network_statistics()
            print(f"[MAIN] Network: {stats['num_nodes']} nodes, "
                  f"{stats['num_edges']} edges, "
                  f"{stats['num_components']} components")

    if args.mutual:
        f1 = _snap_list(h, args.mutual[0], "followers")
        f2 = _snap_list(h, args.mutual[1], "followers")
        if f1 is None or f2 is None:
            print("[MAIN] Need followers snapshots for BOTH users. Harvest first.")
        else:
            ga = GraphAnalyzer()
            r = ga.find_mutual_connections(args.mutual[0], args.mutual[1], f1, f2)
            print(f"[MAIN] Mutual: {r['mutual_count']} "
                  f"(Jaccard {r['jaccard_similarity']})")
            print(f"[MAIN] Sample: {r['mutual_followers'][:10]}")

    if args.temporal:
        posts = _snap_list(h, args.username, "posts")
        if posts is None:
            print("[MAIN] No posts snapshot. Run harvest first.")
        else:
            tp = TemporalProfiler()
            tp.load_posts_data(posts)
            hm = tp.generate_activity_heatmap()
            print(f"[MAIN] Peak: {hm['peak_activity']['day']} "
                  f"{hm['peak_activity']['hour_utc']} UTC")
            caps = tp.analyze_caption_patterns()
            if "error" not in caps:
                print(f"[MAIN] Top hashtags: {list(caps['top_hashtags'])[:8]}")
            tp.export_heatmap_csv(f"{args.username}_heatmap.csv", out)
            tp.generate_temporal_report(f"{args.username}_temporal_report.json", out)


def cmd_media(args):
    h = InstagramHarvester(str(args.base_path))
    posts = _snap_list(h, args.username, "posts")
    if posts is None:
        print("[MAIN] No posts snapshot. Run harvest first.")
        return
    posts = posts[:args.limit]
    dl = MediaDownloader(str(args.base_path))

    if args.download:
        results = dl.batch_download_posts(posts, args.username)
        ok = sum(1 for r in results if r["success"])
        stats = dl.get_download_statistics(args.username)
        print(f"[MAIN] Downloaded {ok}/{len(results)} | "
              f"{stats.get('total_size_mb', 0)} MB on disk")

    if args.exif:
        user_dir = dl.media_dir / MediaDownloader._safe_name(args.username)
        files = []
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            files += sorted(user_dir.glob(f"*{ext}"))
        if not files:
            print("[MAIN] No downloaded images found. Run --download first.")
            return
        ex = EXIFExtractor()
        ex.batch_extract_exif([str(p) for p in files])
        timeline = ex.generate_location_timeline(posts)
        if args.location_timeline:
            ex.export_location_csv(
                timeline, f"{args.username}_location_timeline.csv",
                str(args.out_path))
        ex.export_exif_report(f"{args.username}_exif_report.json",
                              str(args.out_path), posts=posts)


def cmd_monitor(args):
    det = ChangeDetector(str(args.base_path))
    if args.check:
        h = InstagramHarvester(str(args.base_path))
        if args.cookies:
            h.load_session_cookies(args.cookies)
        profile = h.fetch_user_profile(args.username)
        posts = h.fetch_user_posts(args.username, 30)
        result = det.detect_changes(args.username, profile, posts)
        for c in result.get("changes_detected", []):
            print(f"  {SEVERITY_ICON.get(c['severity'], '[LOW ]')} "
                  f"{c['description']}")
    if args.report:
        det.generate_monitoring_report(args.username)
    if args.setup_continuous:
        det.setup_continuous_monitoring(args.username, args.interval)


def cmd_compare(args):
    h = InstagramHarvester(str(args.base_path))
    if args.mutual_followers:
        f1 = _snap_list(h, args.username1, "followers")
        f2 = _snap_list(h, args.username2, "followers")
        if f1 is None or f2 is None:
            print("[MAIN] Need followers snapshots for BOTH users. Harvest first.")
        else:
            ga = GraphAnalyzer()
            r = ga.find_mutual_connections(args.username1, args.username2, f1, f2)
            print(f"[MAIN] Mutual followers: {r['mutual_count']}")
            print(f"[MAIN] Jaccard similarity: {r['jaccard_similarity']}")
            print(f"[MAIN] Unique to @{args.username1}: "
                  f"{len(r['unique_to_username1'])}")
            print(f"[MAIN] Unique to @{args.username2}: "
                  f"{len(r['unique_to_username2'])}")
    if args.network_comparison:
        for user in (args.username1, args.username2):
            followers = _snap_list(h, user, "followers")
            following = _snap_list(h, user, "following")
            if followers is None or following is None:
                print(f"[MAIN] No network snapshots for @{user}.")
                continue
            ga = GraphAnalyzer()
            ga.build_network_from_followers(user, followers, following)
            stats = ga.get_network_statistics()
            print(f"[MAIN] @{user}: {stats['num_nodes']} nodes, "
                  f"{stats['num_edges']} edges, density {stats['density']}")


def main():
    parser = setup_argument_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    base = Path(args.base_dir).expanduser() if args.base_dir \
        else Path(__file__).resolve().parent
    args.base_path = base
    args.out_path = Path(args.output_dir).expanduser() if args.output_dir \
        else base / "output"
    args.out_path.mkdir(parents=True, exist_ok=True)

    print(f"IG-OSINT-ENGINE v1.0.0 | {datetime.now(timezone.utc).isoformat()}")
    handlers = {"harvest": cmd_harvest, "analyze": cmd_analyze,
                "media": cmd_media, "monitor": cmd_monitor,
                "compare": cmd_compare}
    try:
        handlers[args.command](args)
    except KeyboardInterrupt:
        print("\n[MAIN] Cancelled by user.")
    except (HarvestError, ValueError) as exc:
        print(f"[MAIN] Error: {exc}")
        sys.exit(1)
    except Exception as exc:
        if args.verbose:
            raise
        print(f"[MAIN] Unexpected error: {exc} (use --verbose for traceback)")
        sys.exit(1)


if __name__ == "__main__":
    main()
