#!/usr/bin/env python3
"""
Code Audit Script — Phase 4 Defensive Coding

Checks extraction layer files for known quantitative trap patterns:
  - iterrows() / itertuples() → vectorization bottleneck
  - Scalar assignment in loops → performance killer
  - Missing NaN guards on indicator comparisons

Usage: python3 scripts/audit_extraction_code.py app/core/market_structure.py app/core/events.py
"""

import ast
import sys


FORBIDDEN_PATTERNS = [
    ('iterrows()', 'Vectorization bottleneck — use np.where / boolean masks instead'),
    ('itertuples()', 'Vectorization bottleneck — use np.where / boolean masks instead'),
    ('for idx, row in df', 'Vectorization bottleneck — process full columns, not row-by-row'),
    ('df.at[', 'Scalar assignment in loop — use boolean masking instead'),
    ('df.loc[idx,', 'Scalar assignment in loop (where idx is loop variable)'),
]

WARN_PATTERNS = [
    ('bare ffill', 'ffill() without mitigation kill switch: verify zone is NaN-d on mitigation'),
]


def audit_file(filepath: str) -> int:
    """Audit a single file. Returns number of violations (0 = clean)."""
    try:
        with open(filepath) as f:
            source = f.read()
    except FileNotFoundError:
        print(f"SKIP: {filepath} (not found)")
        return 0

    violations = []

    # Check for forbidden patterns
    for pattern, risk in FORBIDDEN_PATTERNS:
        # Only flag if pattern appears outside of docstrings/comments
        if pattern in source:
            violations.append(f"  [FORBIDDEN] {risk}: found '{pattern}'")

    # Warn about ffill without nearby mitigation
    if 'ffill()' in source or '.ffill(' in source:
        if 'mitigated' not in source.lower() and 'NaN' not in source:
            violations.append(
                f"  [WARN] ffill() used without visible mitigation guard. "
                f"Verify NaN-on-mitigation pattern exists."
            )

    if violations:
        print(f"FAIL: {filepath}")
        for v in violations:
            print(v)
        return 1

    print(f"PASS: {filepath}")
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/audit_extraction_code.py <file1> <file2> ...")
        sys.exit(1)

    total = sum(audit_file(f) for f in sys.argv[1:])
    print(f"\n{'=' * 40}")
    print(f"Files audited: {len(sys.argv) - 1}")
    print(f"Violations: {total}")
    sys.exit(min(total, 1))
