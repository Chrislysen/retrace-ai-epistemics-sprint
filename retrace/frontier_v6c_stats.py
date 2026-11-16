"""Paired case-level statistics. No inference calls or artificial draw-level N."""
from __future__ import annotations

from collections import defaultdict
from math import comb, isfinite
from random import Random


def exact_mcnemar(a, b):
    """Two-sided exact conditional binomial test of binary paired outcomes."""
    a, b = list(a), list(b)
    if len(a) != len(b) or not a or any(type(x) is not bool for x in a + b):
        raise ValueError('Equal nonempty Boolean pairs required')
    a_only = sum(x and not y for x, y in zip(a, b))
    b_only = sum(y and not x for x, y in zip(a, b))
    discordant = a_only + b_only
    tail = sum(comb(discordant, k) for k in range(min(a_only, b_only) + 1))
    return {'n_pairs': len(a), 'a_only': a_only, 'b_only': b_only,
            'both_correct': sum(x and y for x, y in zip(a, b)),
            'neither_correct': sum(not x and not y for x, y in zip(a, b)),
            'discordant': discordant,
            'p_two_sided_exact': min(1.0, 2 * tail / (2 ** discordant))}


def holm_adjust(p_values):
    """Holm familywise adjustment in original order; family is fixed prospectively."""
    if any(not isinstance(p, (float, int)) or not isfinite(p) or not 0 <= p <= 1 for p in p_values):
        raise ValueError('Finite p values required')
    out = [None] * len(p_values)
    previous = 0.0
    for rank, (index, value) in enumerate(sorted(enumerate(p_values), key=lambda row: row[1])):
        previous = max(previous, min(1.0, (len(p_values) - rank) * value))
        out[index] = previous
    return out


def case_cluster_bootstrap(rows, *, seed=2026111409, repeats=10000):
    """Resample base cases within fixed families, keeping all paired measures together.

    A row is {case_id, family, metrics:{name:scalar}}. Repeated draws/decisions
    must already be aggregated within a case; duplicate case IDs are rejected.
    The target weights families by their number of cases in this authored set.
    """
    if not rows or type(repeats) is not int or repeats < 1:
        raise ValueError('Nonempty cases and positive repeats required')
    seen, families, metric_names = set(), defaultdict(list), None
    for row in rows:
        if not isinstance(row.get('case_id'), str) or row['case_id'] in seen:
            raise ValueError('Each base case occurs once')
        seen.add(row['case_id'])
        if not isinstance(row.get('family'), str) or not isinstance(row.get('metrics'), dict) or not row['metrics']:
            raise ValueError('Family and metrics required')
        names = set(row['metrics'])
        if metric_names is not None and names != metric_names:
            raise ValueError('Every case needs the same paired metrics')
        metric_names = names
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in row['metrics'].values()):
            raise ValueError('Metrics must be finite; missing outcomes need explicit policy')
        families[row['family']].append(row)
    n, names, rng = len(rows), sorted(metric_names), Random(seed)
    estimates = {name: sum(row['metrics'][name] for row in rows) / n for name in names}
    distributions = {name: [] for name in names}
    ordered = [sorted(families[key], key=lambda row: row['case_id']) for key in sorted(families)]
    for _ in range(repeats):
        sample = [rng.choice(group) for group in ordered for _ in range(len(group))]
        for name in names:
            distributions[name].append(sum(row['metrics'][name] for row in sample) / n)
    def quantile(values, q):
        values = sorted(values)
        index = q * (len(values) - 1)
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (index - lower) * (values[upper] - values[lower])
    return {'unit': 'base_case', 'n_base_cases': n, 'replicates': repeats, 'seed': seed,
            'family_counts': {k: len(families[k]) for k in sorted(families)},
            'metrics': {name: {'estimate': estimates[name],
                              'percentile_95_interval': [quantile(distributions[name], .025),
                                                         quantile(distributions[name], .975)]} for name in names},
            'scope': 'Within-family case-resampling intervals for this authored benchmark; not population sampling confidence or independent draw-level evidence.'}


def mcnemar_design_power(n, discordance, effect, *, alpha=.05):
    """Exact design sensitivity under an explicit iid paired Bernoulli alternative.

    effect=P(B correct)-P(A correct); discordance=P(A only or B only).
    These are planning assumptions, not estimates or claims of actual power.
    """
    if type(n) is not int or n < 1 or not 0 < discordance <= 1 or not abs(effect) <= discordance or not 0 < alpha < 1:
        raise ValueError('Invalid planning assumptions')
    conditional_b = (discordance + effect) / (2 * discordance)
    power = 0.0
    for m in range(n + 1):
        p_m = comb(n, m) * discordance ** m * (1 - discordance) ** (n - m)
        for b_only in range(m + 1):
            p_value = min(1.0, 2 * sum(comb(m, k) for k in range(min(b_only, m - b_only) + 1)) / 2 ** m)
            if p_value <= alpha:
                power += p_m * comb(m, b_only) * conditional_b ** b_only * (1 - conditional_b) ** (m - b_only)
    return power
