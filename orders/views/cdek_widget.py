import hashlib
import json

import requests

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


SERVICE_VERSION = '3.11.1'
AUTH_CACHE_PREFIX = 'orders:cdek_widget:token:'
HTTP_TIMEOUT_SECONDS = 15


def _json_error(message, *, status=400):
    response = JsonResponse({'message': message}, status=status)
    response['X-Service-Version'] = SERVICE_VERSION
    return response


def _extract_payload(request):
    payload = dict(request.GET.items())
    if request.body:
        try:
            body_payload = json.loads(request.body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(body_payload, dict):
            return None
        payload.update(body_payload)
    return payload


def _build_cache_key():
    key_material = '||'.join([
        getattr(settings, 'CDEK_WIDGET_ACCOUNT', '').strip(),
        getattr(settings, 'CDEK_WIDGET_PASSWORD', '').strip(),
        getattr(settings, 'CDEK_WIDGET_API_BASE', '').strip(),
    ])
    return AUTH_CACHE_PREFIX + hashlib.sha256(key_material.encode('utf-8')).hexdigest()


def _get_auth_token():
    cache_key = _build_cache_key()
    cached_token = cache.get(cache_key)
    if cached_token:
        return cached_token

    response = requests.post(
        f"{settings.CDEK_WIDGET_API_BASE}/oauth/token",
        data={
            'grant_type': 'client_credentials',
            'client_id': settings.CDEK_WIDGET_ACCOUNT,
            'client_secret': settings.CDEK_WIDGET_PASSWORD,
        },
        headers={
            'Accept': 'application/json',
            'X-App-Name': 'widget_pvz',
            'X-App-Version': SERVICE_VERSION,
            'User-Agent': f'widget/{SERVICE_VERSION}',
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        payload = response.json() or {}
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Server not authorized to CDEK API') from exc
    token = (payload.get('access_token') or '').strip()
    expires_in = int(payload.get('expires_in') or 0)
    if not token:
        raise RuntimeError('Server not authorized to CDEK API')
    ttl = max(expires_in - 60, 60) if expires_in else 3000
    cache.set(cache_key, token, ttl)
    return token


def _pass_through_headers(source_response, target_response):
    target_response['X-Service-Version'] = SERVICE_VERSION
    for header, value in source_response.headers.items():
        if header.lower().startswith('x-'):
            target_response[header] = value
    return target_response


def _proxy_to_cdek(payload):
    action = payload.get('action')
    token = _get_auth_token()
    common_headers = {
        'Accept': 'application/json',
        'Authorization': f'Bearer {token}',
        'X-App-Name': 'widget_pvz',
        'X-App-Version': SERVICE_VERSION,
        'User-Agent': f'widget/{SERVICE_VERSION}',
    }

    if action == 'offices':
        response = requests.get(
            f"{settings.CDEK_WIDGET_API_BASE}/deliverypoints",
            params=payload,
            headers=common_headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    elif action == 'cities':
        city_payload = dict(payload)
        city_payload.pop('action', None)
        if 'country_code' in city_payload and 'country_codes' not in city_payload:
            city_payload['country_codes'] = city_payload.pop('country_code')
        response = requests.get(
            f"{settings.CDEK_WIDGET_API_BASE}/location/cities",
            params=city_payload,
            headers=common_headers,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    elif action == 'calculate':
        response = requests.post(
            f"{settings.CDEK_WIDGET_API_BASE}/calculator/tarifflist",
            json=payload,
            headers={**common_headers, 'Content-Type': 'application/json'},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    else:
        return None

    response.raise_for_status()
    target_response = HttpResponse(response.text, content_type='application/json', status=200)
    return _pass_through_headers(response, target_response)


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def cdek_widget_service_view(request):
    if not getattr(settings, 'CDEK_WIDGET_ACCOUNT', '').strip():
        return _json_error('CDEK widget integration is not configured', status=503)
    if not getattr(settings, 'CDEK_WIDGET_PASSWORD', '').strip():
        return _json_error('CDEK widget integration is not configured', status=503)

    payload = _extract_payload(request)
    if payload is None:
        return _json_error('Invalid JSON body')
    if 'action' not in payload:
        return _json_error('Action is required')
    if payload.get('action') not in {'offices', 'cities', 'calculate'}:
        return _json_error('Unknown action')

    try:
        return _proxy_to_cdek(payload)
    except requests.RequestException:
        return _json_error('CDEK widget upstream request failed', status=502)
    except RuntimeError as exc:
        return _json_error(str(exc), status=502)
