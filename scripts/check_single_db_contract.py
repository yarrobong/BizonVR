#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    import django

    django.setup()

    from manager_portal.single_db_contract import collect_single_db_contract_violations

    violations = collect_single_db_contract_violations(repo_root)
    if violations:
        for violation in violations:
            print(f'- {violation}', file=sys.stderr)
        return 1
    print('Single-DB contract is satisfied.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
