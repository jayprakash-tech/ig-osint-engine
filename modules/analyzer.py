"""Instagram Analyzer Module.

Pillar 1: Graph/network mapping (networkx).
Pillar 2: Temporal behavioral profiling (pandas), UTC-normalized.

Works fully offline on harvested JSON snapshots - no cookies needed.
"""

import json
import re
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx
import numpy as np
import pandas as pd

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
             "Friday", "Saturday", "Sunday"]

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are",
    "was", "but", "not", "have", "has", "had", "its", "our", "out",
    "all", "just", "can", "will", "from", "they", "them", "their",
    "what", "when", "who", "how", "why", "been", "were", "than",
}


class GraphAnalyzer:
    """Network mapping, mutual connections, communities, centrality."""

    def __init__(self):
        self.graph = nx.Graph()

    # ---------------- Pillar 1 ----------------

    def build_network_from_followers(self, target: str,
                                     followers_list: List[Dict],
                                     following_list: List[Dict]) -> nx.Graph:
        self.graph = nx.Graph()
        meta = {}
        for rec in list(followers_list) + list(following_list):
            if rec.get("username"):
                meta[rec["username"]] = rec
        fset = {r["username"] for r in followers_list if r.get("username")}
        gset = {r["username"] for r in following_list if r.get("username")}

        self.graph.add_node(target, type="target", is_verified=False)
        for user in sorted(fset | gset):
            if user in fset and user in gset:
                ntype = "mutual"
            elif user in fset:
                ntype = "follower"
            else:
                ntype = "following"
            self.graph.add_node(
                user, type=ntype,
                is_verified=bool(meta[user].get("is_verified", False)),
            )
            self.graph.add_edge(target, user, relationship="connection")

        print(f"[GRAPH] Built: {self.graph.number_of_nodes()} nodes, "
              f"{self.graph.number_of_edges()} edges "
              f"({len(fset & gset)} mutuals of @{target})")
        return self.graph

    def find_mutual_connections(self, username1: str, username2: str,
                                followers1: List[Dict],
                                followers2: List[Dict]) -> Dict:
        set1 = {f["username"] for f in followers1 if f.get("username")}
        set2 = {f["username"] for f in followers2 if f.get("username")}
        mutual = set1 & set2
        union = set1 | set2
        jaccard = len(mutual) / len(union) if union else 0.0
        result = {
            "username1": username1,
            "username2": username2,
            "mutual_count": len(mutual),
            "mutual_followers": sorted(mutual),
            "unique_to_username1": sorted(set1 - set2),
            "unique_to_username2": sorted(set2 - set1),
            "jaccard_similarity": round(jaccard, 4),
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"[GRAPH] @{username1} <-> @{username2}: "
              f"{len(mutual)} mutuals (Jaccard {jaccard:.4f})")
        return result

    def build_shared_follower_graph(self, follower_map: Dict[str, List[Dict]],
                                    include_followers: bool = False) -> nx.Graph:
        """Connect multiple targets by shared-follower overlap weight."""
        graph = nx.Graph()
        sets = {}
        for target, followers in follower_map.items():
            sets[target] = {f["username"] for f in followers if f.get("username")}
            graph.add_node(target, type="target", is_verified=False)
        for a, b in combinations(sorted(sets), 2):
            shared = len(sets[a] & sets[b])
            if shared > 0:
                graph.add_edge(a, b, weight=shared)
        if include_followers:
            for target, users in sets.items():
                for user in users:
                    if not graph.has_node(user):
                        graph.add_node(user, type="follower", is_verified=False)
                    graph.add_edge(target, user, weight=1)
        self.graph = graph
        print(f"[GRAPH] Shared-follower graph: {graph.number_of_nodes()} nodes, "
              f"{graph.number_of_edges()} edges")
        return graph

    def detect_communities(self) -> Dict:
        if self.graph.number_of_nodes() == 0:
            raise ValueError("Graph is empty. Build a network first.")
        communities = nx.community.greedy_modularity_communities(
            self.graph, weight="weight")
        communities = sorted(communities, key=len, reverse=True)
        analysis = {
            "num_communities": len(communities),
            "modularity": round(
                nx.community.modularity(self.graph, communities, weight="weight"), 4),
            "communities": [],
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for i, members in enumerate(communities):
            analysis["communities"].append({
                "community_id": i,
                "size": len(members),
                "members": sorted(members),
                "density": round(nx.density(self.graph.subgraph(members)), 4),
            })
        print(f"[GRAPH] {len(communities)} communities "
              f"(modularity {analysis['modularity']})")
        return analysis

    def find_influential_nodes(self, top_n: int = 10) -> List[Dict]:
        if self.graph.number_of_nodes() == 0:
            raise ValueError("Graph is empty. Build a network first.")
        n = self.graph.number_of_nodes()
        k = min(100, n)  # sampled betweenness: fast on phones
        degree = nx.degree_centrality(self.graph)
        between = nx.betweenness_centrality(self.graph, k=k, seed=42, weight="weight")
        close = nx.closeness_centrality(self.graph)
        scores = {u: 0.4 * degree[u] + 0.3 * between[u] + 0.3 * close[u]
                  for u in self.graph.nodes()}
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
        results = []
        for user, score in top:
            attrs = self.graph.nodes[user]
            results.append({
                "username": user,
                "combined_score": round(score, 4),
                "degree_centrality": round(degree[user], 4),
                "betweenness_centrality": round(between[user], 4),
                "closeness_centrality": round(close[user], 4),
                "node_type": attrs.get("type", "unknown"),
                "is_verified": bool(attrs.get("is_verified", False)),
            })
        return results

    def export_graphml(self, filename: str = "network.graphml",
                       output_dir: str = "~/ig_toolkit/output") -> str:
        if self.graph.number_of_nodes() == 0:
            raise ValueError("Graph is empty. Build a network first.")
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        nx.write_graphml(self.graph, path)
        print(f"[GRAPH] GraphML exported: {path}")
        return str(path)

    def get_network_statistics(self) -> Dict:
        g = self.graph
        if g.number_of_nodes() == 0:
            raise ValueError("Graph is empty. Build a network first.")
        return {
            "num_nodes": g.number_of_nodes(),
            "num_edges": g.number_of_edges(),
            "density": round(nx.density(g), 4),
            "average_clustering": round(nx.average_clustering(g), 4),
            "average_degree": round(
                sum(d for _, d in g.degree()) / g.number_of_nodes(), 4),
            "is_connected": nx.is_connected(g),
            "num_components": nx.number_connected_components(g),
        }


class TemporalProfiler:
    """Pillar 2: UTC-normalized activity heatmaps and caption forensics."""

    def __init__(self):
        self.posts_data: List[Dict] = []
        self._df: Optional[pd.DataFrame] = None

    def load_posts_data(self, posts_list: List[Dict]):
        rows = []
        for post in posts_list:
            ts = post.get("timestamp")
            dt = None
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
            if dt is None:
                continue
            rows.append({
                "datetime": dt,
                "day_of_week": dt.weekday(),
                "hour_of_day": dt.hour,
                "caption": post.get("caption") or "",
                "likes": int(post.get("like_count") or 0),
                "comments": int(post.get("comment_count") or 0),
                "location_name": (post.get("location") or {}).get("name"),
            })
        self.posts_data = rows
        self._df = pd.DataFrame(rows)
        print(f"[TEMPORAL] Loaded {len(rows)} posts (all hours normalized to UTC)")

    def _require_data(self):
        if not self.posts_data:
            raise ValueError("No posts loaded. Run load_posts_data() first.")

    def _heatmap_frame(self) -> pd.DataFrame:
        ct = pd.crosstab(self._df["day_of_week"], self._df["hour_of_day"])
        return ct.reindex(index=range(7), columns=range(24), fill_value=0)

    def generate_activity_heatmap(self) -> Dict:
        self._require_data()
        matrix = self._heatmap_frame().to_numpy().astype(int)
        total = int(matrix.sum())
        peak_day, peak_hour = np.unravel_index(int(matrix.argmax()), matrix.shape)

        daily = {}
        for d in range(7):
            day_total = int(matrix[d].sum())
            daily[DAY_NAMES[d]] = {
                "total_posts": day_total,
                "percentage": round(100.0 * day_total / total, 2),
                "peak_hour": int(matrix[d].argmax()) if day_total else None,
            }
        hourly = {}
        hourly_totals = []
        for h in range(24):
            hour_total = int(matrix[:, h].sum())
            hourly_totals.append(hour_total)
            hourly[f"{h:02d}:00"] = {
                "total_posts": hour_total,
                "percentage": round(100.0 * hour_total / total, 2),
            }
        return {
            "heatmap_matrix_utc": matrix.tolist(),
            "peak_activity": {
                "day": DAY_NAMES[int(peak_day)],
                "hour_utc": f"{int(peak_hour):02d}:00",
                "post_count": int(matrix[peak_day][peak_hour]),
            },
            "daily_activity": daily,
            "hourly_activity_utc": hourly,
            "timezone_insights": self._infer_timezone(hourly_totals),
            "total_posts_analyzed": total,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _infer_timezone(hourly_totals: List[int]) -> Dict:
        """Heuristic only: find quietest 8h window, assume ~23:00 local sleep start."""
        total = sum(hourly_totals)
        if total == 0:
            return {"confidence": "none"}
        best_start, best_sum = 0, None
        for start in range(24):
            window = sum(hourly_totals[(start + i) % 24] for i in range(8))
            if best_sum is None or window < best_sum:
                best_start, best_sum = start, window
        offset = (best_start - 23) % 24
        if offset > 12:
            offset -= 24
        quiet_ratio = best_sum / total
        return {
            "quiet_window_utc": f"{best_start:02d}:00-{(best_start + 8) % 24:02d}:00",
            "estimated_utc_offset_hours": offset,
            "confidence": "medium" if quiet_ratio < 0.15 else "low",
            "caveat": "Heuristic estimate from posting gaps, not proof of location.",
        }

    def analyze_caption_patterns(self) -> Dict:
        self._require_data()
        captions = [r["caption"] for r in self.posts_data if r["caption"]]
        if not captions:
            return {"error": "No captions found", "total_captions": 0}
        words, hashtags, mentions = Counter(), Counter(), Counter()
        for cap in captions:
            low = cap.lower()
            hashtags.update(re.findall(r"#(\w+)", low))
            mentions.update(re.findall(r"@([a-z0-9._]+)", low))
            clean = re.sub(r"[#@]\w+", " ", low)
            words.update(w for w in re.findall(r"[a-z']{3,}", clean)
                         if w not in STOPWORDS)
        lengths = [len(c) for c in captions]
        locations = Counter(r["location_name"] for r in self.posts_data
                            if r["location_name"])
        return {
            "total_captions": len(captions),
            "avg_caption_length": round(sum(lengths) / len(lengths), 2),
            "max_caption_length": max(lengths),
            "top_words": dict(words.most_common(20)),
            "top_hashtags": dict(hashtags.most_common(15)),
            "top_mentions": dict(mentions.most_common(10)),
            "top_geotag_locations": dict(locations.most_common(10)),
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def export_heatmap_csv(self, filename: str = "heatmap.csv",
                           output_dir: str = "~/ig_toolkit/output") -> str:
        self._require_data()
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        frame = self._heatmap_frame()
        frame.index = [DAY_NAMES[i] for i in frame.index]
        frame.columns = [f"{h:02d}" for h in frame.columns]
        path = out / filename
        frame.to_csv(path, index_label="day_utc")
        print(f"[TEMPORAL] Heatmap CSV exported: {path}")
        return str(path)

    def generate_temporal_report(self, output_file: str = "temporal_report.json",
                                 output_dir: str = "~/ig_toolkit/output") -> str:
        self._require_data()
        report = {
            "activity_heatmap": self.generate_activity_heatmap(),
            "caption_patterns": self.analyze_caption_patterns(),
            "metadata": {
                "total_posts": len(self.posts_data),
                "date_range_utc": {
                    "earliest": min(r["datetime"] for r in self.posts_data).isoformat(),
                    "latest": max(r["datetime"] for r in self.posts_data).isoformat(),
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        out = Path(output_dir).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        path = out / output_file
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"[TEMPORAL] Report saved: {path}")
        return str(path)
