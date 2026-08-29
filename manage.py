#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def _use_test_settings_by_default():
    """Use isolated settings for plain ``manage.py test`` invocations only."""
    if sys.argv[1:2] != ['test'] or 'DJANGO_SETTINGS_MODULE' in os.environ:
        return False
    return not any(
        argument == '--settings' or argument.startswith('--settings=')
        for argument in sys.argv[1:]
    )


def main():
    """Run administrative tasks."""
    if _use_test_settings_by_default():
        os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings_test'
    else:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
