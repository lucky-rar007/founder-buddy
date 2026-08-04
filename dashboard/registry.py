"""
Self-healing Signal Type & Cluster Registry.

Uses Levenshtein distance-based fuzzy matching to prevent duplicate
entries when the LLM proposes event types that are close to existing ones.

Adapted from the learning project's event_matcher.py.
"""

import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")


from typing import Any

# ─────────────────────────────────────────────────────────────────────
# LEVENSHTEIN DISTANCE (from learning project)
# ─────────────────────────────────────────────────────────────────────

def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Computes the Levenshtein distance between two strings.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def string_similarity(s1: str, s2: str) -> float:
    """
    Computes similarity ratio between two strings based on Levenshtein distance.
    Range: 0.0 (completely different) to 1.0 (identical).
    """
    s1 = s1.lower().strip().replace('_', ' ').replace('-', ' ')
    s2 = s2.lower().strip().replace('_', ' ').replace('-', ' ')

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))

    if max_len == 0:
        return 1.0

    return 1.0 - (distance / max_len)


# ─────────────────────────────────────────────────────────────────────
# SIGNAL TYPE REGISTRY MATCHER
# ─────────────────────────────────────────────────────────────────────

def match_and_register_signal_type(
    registry: dict[str, dict[str, str]],
    proposed_type: str,
    description: str,
    category: str
) -> str:
    """
    Compares the proposed signal type with all types in the in-memory registry.
    If a close match (similarity >= 0.85) exists, maps to that match.
    Otherwise, registers the new signal type in the registry.
    Returns the resolved signal type name.
    """
    proposed_type = proposed_type.strip().lower().replace(' ', '_').replace('-', '_')

    # Exact match first
    if proposed_type in registry:
        return proposed_type

    best_match = None
    max_similarity = 0.0

    for existing_type in registry.keys():
        sim = string_similarity(proposed_type, existing_type)
        if sim > max_similarity:
            max_similarity = sim
            best_match = existing_type

    # Threshold: 0.85 (same as learning project)
    if max_similarity >= 0.85 and best_match:
        logging.info(f"    [Registry] Mapped proposed signal '{proposed_type}' → existing '{best_match}' (similarity: {max_similarity:.2f})")
        return best_match
    else:
        logging.info(f"    [Registry] No close match found. Registering new signal type: '{proposed_type}' (category: '{category}')")
        registry[proposed_type] = {
            "description": description.strip(),
            "category": category.strip()
        }
        # Persist to database
        try:
            from dashboard.db import add_signal_type
            add_signal_type(proposed_type, category, description)
        except Exception as e:
            logging.error(f"    [Registry Error] Failed to persist new signal type to DB: {e}")
        return proposed_type


# ─────────────────────────────────────────────────────────────────────
# CLUSTER REGISTRY MATCHER
# ─────────────────────────────────────────────────────────────────────

def match_and_register_cluster(
    cluster_registry: dict[str, dict[str, Any]],
    proposed_cluster: str,
    description: str,
    category: str,
    persistence: float = 0.6,
    decay_rate: float = 0.02
) -> str:
    """
    Same fuzzy-matching logic but for cluster types.
    Returns the resolved cluster type name.
    """
    proposed_cluster = proposed_cluster.strip().lower().replace(' ', '_').replace('-', '_')

    if proposed_cluster in cluster_registry:
        return proposed_cluster

    best_match = None
    max_similarity = 0.0

    for existing_type in cluster_registry.keys():
        sim = string_similarity(proposed_cluster, existing_type)
        if sim > max_similarity:
            max_similarity = sim
            best_match = existing_type

    if max_similarity >= 0.85:
        logging.info(f"    [Registry] Mapped proposed cluster '{proposed_cluster}' → existing '{best_match}' (similarity: {max_similarity:.2f})")
        return best_match
    else:
        logging.info(f"    [Registry] Registering new cluster: '{proposed_cluster}' (category: '{category}')")
        cluster_registry[proposed_cluster] = {
            "description": description.strip(),
            "category": category.strip(),
            "persistence": persistence,
            "decay_rate": decay_rate
        }
        try:
            from dashboard.db import add_cluster
            add_cluster(proposed_cluster, category, description, persistence, decay_rate)
        except Exception as e:
            logging.error(f"    [Registry Error] Failed to persist new cluster to DB: {e}")
        return proposed_cluster
