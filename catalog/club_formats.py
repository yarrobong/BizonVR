FORMAT_ARCADE = 'arcade'
FORMAT_CLUB = 'club'
FORMAT_ARENA = 'arena'
FORMAT_HOME = 'home'
FORMAT_KIDS = 'kids'
FORMAT_PARTY = 'party'
FORMAT_MOBILE = 'mobile'

FORMAT_CHOICES = [
    (FORMAT_ARCADE, 'Аркада / ТЦ'),
    (FORMAT_CLUB, 'VR-клуб'),
    (FORMAT_ARENA, 'Арена'),
    (FORMAT_HOME, 'Дом'),
    (FORMAT_KIDS, 'Дети'),
    (FORMAT_PARTY, 'Вечеринка'),
    (FORMAT_MOBILE, 'Выездной формат'),
]

_FORMAT_ALIASES = {
    FORMAT_ARCADE: FORMAT_ARCADE,
    FORMAT_CLUB: FORMAT_CLUB,
    FORMAT_ARENA: FORMAT_ARENA,
    FORMAT_HOME: FORMAT_HOME,
    FORMAT_KIDS: FORMAT_KIDS,
    FORMAT_PARTY: FORMAT_PARTY,
    FORMAT_MOBILE: FORMAT_MOBILE,
    'Аркада / ТЦ': FORMAT_ARCADE,
    'VR-клуб': FORMAT_CLUB,
    'Арена': FORMAT_ARENA,
    'Дом': FORMAT_HOME,
    'Дети': FORMAT_KIDS,
    'Вечеринка': FORMAT_PARTY,
    'Выездной формат': FORMAT_MOBILE,
    'VR-зона': FORMAT_CLUB,
}


def normalize_club_format(value):
    normalized_value = (value or '').strip()
    if not normalized_value:
        return ''

    try:
        return _FORMAT_ALIASES[normalized_value]
    except KeyError as exc:
        raise ValueError(f'Unknown club format: {normalized_value}') from exc
