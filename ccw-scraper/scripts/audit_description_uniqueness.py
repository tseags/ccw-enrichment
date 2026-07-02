#!/usr/bin/env python3
"""
Audit vendor_description uniqueness across instructor profiles.

Read-only: writes reports to data/audit/.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or ccw-scraper/
_SCRAPER = Path(__file__).resolve().parents[1]
if str(_SCRAPER) not in sys.path:
    sys.path.insert(0, str(_SCRAPER))

from scripts.gsc_profile_utils import (  # noqa: E402
    AUDIT_DIR,
    dedupe_vendors,
    fetch_production_slugs,
    gsc_status_for_url,
    load_corpus_rows,
    load_discovered_not_indexed_urls,
    load_indexed_urls,
    name_to_slug,
    profile_url_from_slug,
    resolve_profile_slug,
    slug_name_part,
)

BOILERPLATE_PHRASES = [
    "comprehensive ccw training",
    "certified instructors",
    "serving",
    "county",
    "16-hour initial",
    "8-hour renewal",
    "offers california ccw certification",
    "california ccw",
    "concealed carry",
    "nra certified",
    "stress-free learning",
    "highly experienced",
]

_WORD_RE = re.compile(r"[a-z']+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _paragraph_count(text: str) -> int:
    if "\n\n" in text:
        return len([p for p in text.split("\n\n") if p.strip()])
    sents = _sentences(text)
    if len(sents) <= 3:
        return 1
    return max(1, math.ceil(len(sents) / 3))


def _normalize_opening(sentence: str) -> str:
    s = sentence.lower().strip()
    s = re.sub(r"\b\d+\b", "{NUM}", s)
    s = re.sub(r"\$[\d,]+", "{PRICE}", s)
    for county in (
        "alameda", "contra costa", "san diego", "los angeles", "orange",
        "riverside", "sacramento", "fresno", "shasta", "sonoma", "napa",
    ):
        s = re.sub(rf"\b{re.escape(county)}\b", "{LOCATION}", s)
    s = re.sub(r"\b[a-z][a-z'-]* county\b", "{COUNTY}", s)
    s = re.sub(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", "{NAME}", sentence.lower())
    s = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "{PHONE}", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _opening_key(text: str, n_words: int = 6) -> str:
    sents = _sentences(text)
    if not sents:
        return ""
    norm = _normalize_opening(sents[0])
    words = norm.split()[:n_words]
    return " ".join(words)


def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _build_tfidf(docs: list[list[str]]) -> tuple[list[dict[str, float]], dict[str, float]]:
    df: Counter[str] = Counter()
    for tokens in docs:
        for t in set(tokens):
            df[t] += 1
    n = len(docs)
    idf = {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in df}
    vectors: list[dict[str, float]] = []
    for tokens in docs:
        tf = Counter(tokens)
        total = sum(tf.values()) or 1
        vec = {t: (c / total) * idf.get(t, 0.0) for t, c in tf.items()}
        vectors.append(vec)
    return vectors, idf


def _cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in vec_a.values()))
    nb = math.sqrt(sum(v * v for v in vec_b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _mean_vector(vectors: list[dict[str, float]]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for v in vectors:
        for k, val in v.items():
            acc[k] += val
    n = len(vectors) or 1
    return {k: val / n for k, val in acc.items()}


def _score_uniqueness(
    idx: int,
    descriptions: list[str],
    opening_clusters: dict[str, int],
    cluster_sizes: Counter,
    tfidf_vecs: list[dict[str, float]],
    centroid: dict[str, float],
    nearest_sim: list[float],
    modal_sent_count: int,
) -> int:
    desc = descriptions[idx]
    sents = _sentences(desc)
    sent_count = len(sents) or 1
    opening = _opening_key(desc)
    cluster_id = opening_clusters.get(opening, -1)
    cluster_size = cluster_sizes.get(cluster_id, 1)

    tfidf_dist = 1.0 - _cosine(tfidf_vecs[idx], centroid)
    nn_sim = nearest_sim[idx]

    sent_pattern_match = 1.0 if abs(sent_count - modal_sent_count) <= 1 else 0.0

    # Weighted signals → 1-5
    if cluster_size <= 2 and tfidf_dist >= 0.35 and nn_sim < 0.45:
        return 5
    if cluster_size <= 5 and tfidf_dist >= 0.25 and nn_sim < 0.55:
        return 4
    if cluster_size <= 15 and nn_sim < 0.65:
        return 3
    if cluster_size <= 40 or nn_sim >= 0.72 or sent_pattern_match:
        return 2
    return 1


def run_audit(refresh_slugs: bool = False) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    indexed_urls = load_indexed_urls()
    discovered_urls = load_discovered_not_indexed_urls()

    print("Loading corpus…")
    rows = load_corpus_rows()
    deduped, county_map = dedupe_vendors(rows)
    print(f"  {len(rows)} rows with descriptions → {len(deduped)} unique vendors")

    print("Resolving production profile slugs…")
    from scripts.gsc_profile_utils import build_slug_index

    slugs = fetch_production_slugs(refresh=refresh_slugs)
    slug_index = build_slug_index(slugs)

    descriptions = [(d.get("vendor_description") or "").strip() for d in deduped]
    tokens_list = [_tokenize(d) for d in descriptions]

    print("Computing TF-IDF and pairwise similarity…")
    tfidf_vecs, _ = _build_tfidf(tokens_list)
    centroid = _mean_vector(tfidf_vecs)

    nearest_sim: list[float] = []
    for i, tokens in enumerate(tokens_list):
        word_set = set(tokens)
        best = 0.0
        for j, other in enumerate(tokens_list):
            if i == j:
                continue
            sim = max(_jaccard(word_set, set(other)), _cosine(tfidf_vecs[i], tfidf_vecs[j]))
            best = max(best, sim)
        nearest_sim.append(best)

    # Opening template clusters
    opening_keys = [_opening_key(d) for d in descriptions]
    opening_freq = Counter(opening_keys)
    cluster_id_map: dict[str, int] = {}
    cluster_sizes: Counter = Counter()
    for i, key in enumerate(sorted(opening_freq.keys(), key=lambda k: (-opening_freq[k], k))):
        cluster_id_map[key] = i
        cluster_sizes[i] = opening_freq[key]

    opening_clusters = {k: cluster_id_map[k] for k in opening_keys}
    sent_counts = [len(_sentences(d)) or 1 for d in descriptions]
    modal_sent_count = Counter(sent_counts).most_common(1)[0][0]

    # Global n-grams
    all_ngrams: Counter = Counter()
    for tokens in tokens_list:
        for n in (3, 4, 5):
            all_ngrams.update(_ngrams(tokens, n))

    scored_rows: list[dict] = []
    for i, d in enumerate(deduped):
        desc = descriptions[i]
        slug, match_method = resolve_profile_slug(
            d["vendor_name"],
            d.get("website_url", ""),
            slug_index=slug_index,
            all_slugs=slugs,
        )
        if match_method == "constructed":
            profile_url = profile_url_from_slug(slug)
        else:
            profile_url = profile_url_from_slug(slug)
        gsc = gsc_status_for_url(profile_url, indexed_urls)

        opening = _opening_key(desc)
        cid = cluster_id_map.get(opening, -1)
        score = _score_uniqueness(
            i, descriptions, opening_clusters, cluster_sizes,
            tfidf_vecs, centroid, nearest_sim, modal_sent_count,
        )

        scored_rows.append({
            "normalized_vendor_name": d["normalized_vendor_name"],
            "vendor_name": d["vendor_name"],
            "profile_url": profile_url,
            "profile_slug": slug,
            "slug_match_method": match_method,
            "gsc_status": gsc,
            "county_rows": d.get("county_rows", 1),
            "counties_served": d.get("counties_served", ""),
            "word_count": len(tokens_list[i]),
            "sentence_count": sent_counts[i],
            "paragraph_count": _paragraph_count(desc),
            "opening_template_cluster_id": cid,
            "opening_template_cluster_size": cluster_sizes.get(cid, 1),
            "nearest_neighbor_similarity": round(nearest_sim[i], 4),
            "uniqueness_score_1_5": score,
            "vendor_description_truncated": desc[:200],
            "vendor_description": desc,
        })

    # Write description-uniqueness-scores.csv
    scores_path = AUDIT_DIR / "description-uniqueness-scores.csv"
    fieldnames = [
        "normalized_vendor_name", "vendor_name", "profile_url", "profile_slug",
        "slug_match_method", "gsc_status", "county_rows", "counties_served",
        "word_count", "sentence_count", "paragraph_count",
        "opening_template_cluster_id", "opening_template_cluster_size",
        "nearest_neighbor_similarity", "uniqueness_score_1_5",
        "vendor_description_truncated",
    ]
    with scores_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(scored_rows)
    print(f"Wrote {scores_path}")

    # priority-fix-list.csv
    priority = [
        r for r in scored_rows
        if r["uniqueness_score_1_5"] <= 3 and r["gsc_status"] != "indexed"
    ]
    if discovered_urls:
        priority = [
            r for r in priority
            if normalize_gsc_url(r["profile_url"]) in discovered_urls
        ]
    priority.sort(key=lambda r: (r["uniqueness_score_1_5"], -r["nearest_neighbor_similarity"]))
    priority_path = AUDIT_DIR / "priority-fix-list.csv"
    with priority_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(priority)
    print(f"Wrote {priority_path} ({len(priority)} fix candidates)")

    # skipped-indexed.csv
    skipped = [
        {
            "normalized_vendor_name": r["normalized_vendor_name"],
            "profile_url": r["profile_url"],
            "uniqueness_score": r["uniqueness_score_1_5"],
            "skip_reason": "indexed_in_gsc_valid_export",
        }
        for r in scored_rows
        if r["uniqueness_score_1_5"] <= 3 and r["gsc_status"] == "indexed"
    ]
    skipped_path = AUDIT_DIR / "skipped-indexed.csv"
    with skipped_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(skipped[0].keys()) if skipped else [
            "normalized_vendor_name", "profile_url", "uniqueness_score", "skip_reason",
        ])
        w.writeheader()
        w.writerows(skipped)
    print(f"Wrote {skipped_path} ({len(skipped)} low-score but indexed)")

    # audit-summary.md
    score_dist = Counter(r["uniqueness_score_1_5"] for r in scored_rows)
    word_counts = [r["word_count"] for r in scored_rows]
    sent_counts_all = [r["sentence_count"] for r in scored_rows]
    word_counts.sort()
    sent_counts_all.sort()
    mid = len(word_counts) // 2

    top_openings: list[tuple[str, int, str]] = []
    for key, cid in sorted(cluster_id_map.items(), key=lambda x: -cluster_sizes[x[1]])[:20]:
        example = next(r["vendor_name"] for r in scored_rows if _opening_key(r["vendor_description"]) == key)
        top_openings.append((key, cluster_sizes[cid], example))

    top_ngrams = all_ngrams.most_common(20)

    indexed_by_score: dict[int, dict[str, int]] = defaultdict(lambda: {"indexed": 0, "not_indexed": 0, "unknown": 0})
    for r in scored_rows:
        s = r["uniqueness_score_1_5"]
        g = r["gsc_status"]
        if g in indexed_by_score[s]:
            indexed_by_score[s][g] += 1
        else:
            indexed_by_score[s]["unknown"] += 1

    fix_candidates = len([r for r in scored_rows if r["uniqueness_score_1_5"] <= 3 and r["gsc_status"] != "indexed"])
    fix_indexed_excluded = len(skipped)
    pct_shared_opening = round(
        100 * sum(1 for r in scored_rows if r["opening_template_cluster_size"] > 15) / max(len(scored_rows), 1),
        1,
    )

    summary_lines = [
        "# Vendor description uniqueness audit",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"- Unique vendors analyzed: **{len(scored_rows)}**",
        f"- Production slugs resolved: **{len(slugs)}**",
        f"- GSC indexed instructor URLs: **{len(indexed_urls)}**",
        f"- Discovered-not-indexed filter: **{'active (' + str(len(discovered_urls)) + ' URLs)' if discovered_urls else 'not provided'}**",
        "",
        "## Score distribution (1=most templated, 5=most unique)",
        "",
    ]
    for s in range(1, 6):
        summary_lines.append(f"- Score {s}: **{score_dist.get(s, 0)}** vendors")
    summary_lines.extend([
        "",
        "## Corpus stats",
        "",
        f"- Mean word count: **{sum(word_counts)/len(word_counts):.1f}**",
        f"- Median word count: **{word_counts[mid]}**",
        f"- Mean sentence count: **{sum(sent_counts_all)/len(sent_counts_all):.1f}**",
        f"- Median sentence count: **{sent_counts_all[mid]}**",
        f"- % sharing opening template (cluster >15): **{pct_shared_opening}%**",
        "",
        "## GSC status by score band",
        "",
        "| Score | Indexed | Not indexed | Unknown |",
        "|------:|--------:|------------:|--------:|",
    ])
    for s in range(1, 6):
        b = indexed_by_score[s]
        summary_lines.append(
            f"| {s} | {b['indexed']} | {b['not_indexed']} | {b['unknown']} |"
        )
    summary_lines.extend([
        "",
        "## Fix scope",
        "",
        f"- Fix candidates (score ≤3, not indexed): **{fix_candidates}**",
        f"- Low-score but indexed (protected): **{fix_indexed_excluded}**",
        "",
        "## Top 20 opening templates",
        "",
    ])
    for i, (tmpl, freq, ex) in enumerate(top_openings, 1):
        summary_lines.append(f"{i}. ({freq}×) `{tmpl}` — e.g. {ex}")
    summary_lines.extend(["", "## Top 20 repeated n-grams", ""])
    for ng, cnt in top_ngrams:
        summary_lines.append(f"- `{' '.join(ng)}` — {cnt}×")
    summary_lines.extend(["", "## Tracked boilerplate prevalence", ""])
    corpus_lower = " ".join(descriptions).lower()
    for phrase in BOILERPLATE_PHRASES:
        cnt = corpus_lower.count(phrase)
        summary_lines.append(f"- \"{phrase}\": **{cnt}** occurrences")

    summary_path = AUDIT_DIR / "audit-summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"Wrote {summary_path}")

    # Persist county map for regeneration
    map_path = AUDIT_DIR / "vendor-county-row-map.csv"
    with map_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["normalized_vendor_name", "county", "row_id", "vendor_name"])
        for key, group in county_map.items():
            for g in group:
                w.writerow([key, g.get("county", ""), g.get("id", ""), g.get("vendor_name", "")])
    print(f"Wrote {map_path}")


def normalize_gsc_url(url: str) -> str:
    from scripts.gsc_profile_utils import normalize_gsc_url as _n
    return _n(url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit vendor_description uniqueness")
    parser.add_argument("--refresh-slugs", action="store_true", help="Re-fetch production instructor slugs")
    args = parser.parse_args()
    run_audit(refresh_slugs=args.refresh_slugs)


if __name__ == "__main__":
    main()
