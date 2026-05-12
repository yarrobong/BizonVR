import sys

from decouple import config


TRUE_VALUES = {'1', 'true', 'yes', 'y', 'on', 'debug', 'development', 'dev'}
FALSE_VALUES = {'0', 'false', 'no', 'n', 'off', 'release', 'production', 'prod'}


def parse_bool_value(value, *, default=False, name='value'):
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized == '':
        return default
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False

    raise ValueError(f'Invalid truth value for {name}: {value}')


def config_bool(name, default=False):
    return parse_bool_value(config(name, default=None), default=default, name=name)


def is_runserver_command(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    normalized_args = {str(arg).strip().lower() for arg in args if str(arg).strip()}
    return bool(normalized_args & {'runserver', 'runserver_plus'})
