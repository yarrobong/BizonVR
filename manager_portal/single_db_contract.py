from __future__ import annotations

from pathlib import Path

from django.conf import settings


ARCHIVED_RUNTIME_NAMES = ('BusinessFinance', 'docuflow (2)')
ALLOWED_SQLITE_ROOTS = ('legacy',)
TEXT_SCAN_ROOTS = (
    'README.md',
    'DEPLOY.md',
    'AGENTS.md',
    'Makefile',
    '.env.example',
    'launchers',
)
TEXT_SCAN_PATTERNS = (
    'streamlit run app.py',
    'npm --prefix server',
    'Start_DocuFlow',
    'Stop_DocuFlow',
    'BusinessFinance/',
    'docuflow (2)/',
)
SKIP_DIR_NAMES = {
    '.git',
    '.venv',
    'venv',
    '__pycache__',
    'node_modules',
    'staticfiles',
    'media',
}
IGNORED_SQLITE_SUBTREES = (
    ('.claude', 'worktrees'),
)


def _is_ignored_sqlite_path(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    return any(parts[:len(prefix)] == prefix for prefix in IGNORED_SQLITE_SUBTREES)


def _is_allowed_sqlite_path(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    return bool(relative.parts and relative.parts[0] in ALLOWED_SQLITE_ROOTS)


def _scan_sqlite_files(repo_root: Path) -> list[str]:
    violations: list[str] = []
    for path in repo_root.rglob('*'):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if not path.is_file():
            continue
        if not path.name.endswith(('.sqlite', '.sqlite3')):
            continue
        if _is_ignored_sqlite_path(path, repo_root):
            continue
        if _is_allowed_sqlite_path(path, repo_root):
            continue
        violations.append(f'persistent sqlite file outside legacy: {path.relative_to(repo_root)}')
    return violations


def _scan_archived_runtime_locations(repo_root: Path) -> list[str]:
    violations: list[str] = []
    for runtime_name in ARCHIVED_RUNTIME_NAMES:
        active_path = repo_root / runtime_name
        archived_path = repo_root / 'legacy' / runtime_name
        if active_path.exists():
            violations.append(f'archived runtime still lives in active tree: {active_path.relative_to(repo_root)}')
        if not archived_path.exists():
            violations.append(f'archived runtime is missing from legacy/: {archived_path.relative_to(repo_root)}')
    return violations


def _iter_text_files(repo_root: Path):
    for entry in TEXT_SCAN_ROOTS:
        path = repo_root / entry
        if path.is_file():
            yield path
            continue
        if path.is_dir():
            for child in path.rglob('*'):
                if child.is_file():
                    yield child


def _scan_text_references(repo_root: Path) -> list[str]:
    violations: list[str] = []
    for path in _iter_text_files(repo_root):
        relative = path.relative_to(repo_root)
        text = path.read_text(encoding='utf-8', errors='ignore')
        for pattern in TEXT_SCAN_PATTERNS:
            if pattern in text:
                violations.append(f'active docs/launchers reference archived runtime "{pattern}" in {relative}')
        if 'DATABASE_ROUTERS' in text:
            violations.append(f'active file references DATABASE_ROUTERS in {relative}')
    return violations


def _scan_django_settings() -> list[str]:
    violations: list[str] = []
    database_keys = sorted(settings.DATABASES.keys())
    if database_keys != ['default']:
        violations.append(f'DATABASES must contain only "default", found {database_keys}')
    default_database = settings.DATABASES.get('default', {})
    engine = (default_database.get('ENGINE') or '').lower()
    if 'postgresql' not in engine:
        violations.append(f'default database engine must be PostgreSQL, found {engine or "<empty>"}')
    if getattr(settings, 'DATABASE_ROUTERS', None):
        violations.append('DATABASE_ROUTERS must be empty')
    return violations


def collect_single_db_contract_violations(repo_root: str | Path | None = None) -> list[str]:
    resolved_root = Path(repo_root or settings.BASE_DIR).resolve()
    violations: list[str] = []
    violations.extend(_scan_django_settings())
    violations.extend(_scan_sqlite_files(resolved_root))
    violations.extend(_scan_archived_runtime_locations(resolved_root))
    violations.extend(_scan_text_references(resolved_root))
    return violations
