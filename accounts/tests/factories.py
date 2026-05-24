from itertools import count

from django.contrib.auth import get_user_model


User = get_user_model()

_user_counter = count(1)


def create_user(**overrides):
    index = next(_user_counter)
    defaults = {
        'username': f'test-user-{index}',
        'email': '',
        'password': 'testpass123',
    }
    defaults.update(overrides)
    password = defaults.pop('password')
    return User.objects.create_user(password=password, **defaults)
