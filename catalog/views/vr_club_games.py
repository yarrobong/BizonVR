import re
import logging

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(*args, **kwargs):
        def decorator(view):
            return view
        return decorator

from config.legal_consent import build_legal_acceptance_payload
from config.utils.spam_protection import check_spam_submission, log_blocked_submission
from integrations.bitrix_site_requests import (
    BitrixSiteRequestSyncError,
    create_site_lead_request,
    send_site_request_to_bitrix,
    summarize_spam_check,
)
from integrations.models import SiteLeadRequest

from ..cart_services import (
    _build_service_item_dict,
    build_custom_game_pack_item_dict,
    get_cart_items,
    save_cart_to_db,
    save_cart_to_session,
)
from ..forms import VRClubQuizForm
from ..models import GamePack, Product, ProductGameMetadata, Service, VRClubQuizRequest

logger = logging.getLogger(__name__)


def _split_filter(value):
    return [part.strip() for part in (value or '').split(',') if part.strip()]


def _comma_token_query(field_name, value):
    escaped_value = re.escape((value or '').strip())
    return Q(**{f'{field_name}__iregex': rf'(^|,\s*){escaped_value}(\s*,|$)'})


def _filter_games(request):
    qs = (
        Product.objects
        .filter(is_active=True, game_metadata__is_active=True)
        .select_related('category', 'game_metadata')
        .order_by('game_metadata__sort_order', 'name')
    )
    device = (request.GET.get('device') or '').strip()
    genre = (request.GET.get('genre') or '').strip()
    age = (request.GET.get('age') or '').strip()
    club_format = (request.GET.get('club_format') or '').strip()
    players = (request.GET.get('players') or '').strip()
    if device:
        qs = qs.filter(_comma_token_query('game_metadata__devices', device))
    if genre:
        qs = qs.filter(_comma_token_query('game_metadata__genres', genre))
    if age:
        qs = qs.filter(game_metadata__age_rating__icontains=age)
    if club_format:
        qs = qs.filter(Q(game_metadata__club_format=club_format) | Q(game_metadata__club_format=''))
    if players:
        try:
            players_count = int(players)
        except (TypeError, ValueError):
            players_count = None
        if players_count:
            qs = qs.filter(game_metadata__min_players__lte=players_count, game_metadata__max_players__gte=players_count)
    return qs


def _filter_packs(request):
    qs = (
        GamePack.objects
        .filter(is_active=True, show_on_vr_club_page=True)
        .select_related('category')
        .prefetch_related('entries__product', 'service_entries__service', 'tags')
        .order_by('sort_order', 'vr_club_tariff', '-created_at')
    )
    device = (request.GET.get('device') or '').strip()
    genre = (request.GET.get('genre') or '').strip()
    club_format = (request.GET.get('club_format') or '').strip()
    package_format = (request.GET.get('package_format') or '').strip()
    players = (request.GET.get('players') or '').strip()
    if device:
        qs = qs.filter(_comma_token_query('devices', device))
    if genre:
        qs = qs.filter(_comma_token_query('genres', genre))
    if club_format:
        qs = qs.filter(Q(club_format=club_format) | Q(club_format=''))
    if package_format:
        qs = qs.filter(package_format=package_format)
    if players:
        try:
            players_count = int(players)
        except (TypeError, ValueError):
            players_count = None
        if players_count:
            qs = qs.filter(Q(players_count__gte=players_count) | Q(players_count__isnull=True))
    return qs


@ratelimit(key='ip', rate='10/m', method='POST', block=False)
def vr_club_games_view(request):
    quiz_sent = False
    quiz_form = VRClubQuizForm()
    if request.method == 'POST':
        spam_result = check_spam_submission(request)
        if spam_result.is_spam:
            log_blocked_submission(request, source='vr_club_quiz', result=spam_result)
            spam_status, spam_reason = summarize_spam_check(spam_result)
            create_site_lead_request(
                request=request,
                source_type=SiteLeadRequest.SOURCE_VR_CLUB,
                name=request.POST.get('name', ''),
                phone=request.POST.get('phone', ''),
                email=request.POST.get('email', ''),
                city='',
                message=request.POST.get('comment', ''),
                spam_status=spam_status,
                spam_reason=spam_reason,
            )
            quiz_form = VRClubQuizForm()
            quiz_sent = True
        else:
            quiz_form = VRClubQuizForm(request.POST)
            if quiz_form.is_valid():
                quiz_request = VRClubQuizRequest.objects.create(
                    name=quiz_form.cleaned_data['name'].strip(),
                    phone=quiz_form.cleaned_data['phone'].strip(),
                    email=(quiz_form.cleaned_data.get('email') or '').strip(),
                    club_format=(quiz_form.cleaned_data.get('club_format') or '').strip(),
                    devices=(quiz_form.cleaned_data.get('devices') or '').strip(),
                    headsets_count=quiz_form.cleaned_data.get('headsets_count'),
                    play_places_count=quiz_form.cleaned_data.get('play_places_count'),
                    audience=(quiz_form.cleaned_data.get('audience') or '').strip(),
                    budget=(quiz_form.cleaned_data.get('budget') or '').strip(),
                    comment=(quiz_form.cleaned_data.get('comment') or '').strip(),
                    **build_legal_acceptance_payload(request),
                )
                spam_status, spam_reason = summarize_spam_check(spam_result)
                site_request = create_site_lead_request(
                    request=request,
                    source_type=SiteLeadRequest.SOURCE_VR_CLUB,
                    name=quiz_request.name,
                    phone=quiz_request.phone,
                    email=quiz_request.email,
                    city='',
                    message='\n'.join(
                        part for part in [
                            quiz_request.comment,
                            f'Формат клуба: {quiz_request.club_format}' if quiz_request.club_format else '',
                            f'Устройства: {quiz_request.devices}' if quiz_request.devices else '',
                            f'Количество шлемов: {quiz_request.headsets_count}' if quiz_request.headsets_count else '',
                            f'Игровых мест: {quiz_request.play_places_count}' if quiz_request.play_places_count else '',
                            f'Аудитория: {quiz_request.audience}' if quiz_request.audience else '',
                            f'Бюджет: {quiz_request.budget}' if quiz_request.budget else '',
                        ] if part
                    ),
                    spam_status=spam_status,
                    spam_reason=spam_reason,
                )
                try:
                    send_site_request_to_bitrix(site_request)
                except BitrixSiteRequestSyncError:
                    logger.exception('Bitrix sync failed for vr_club site request %s.', site_request.pk)
                quiz_form = VRClubQuizForm()
                quiz_sent = True

    has_vr_club_packs = GamePack.objects.filter(is_active=True, show_on_vr_club_page=True).exists()
    tariff_packs = list(_filter_packs(request)[:6])

    games = list(_filter_games(request)[:60])
    services = list(Service.objects.filter(is_active=True, is_vr_club_service=True).order_by('order', 'name'))
    metadata_values = ProductGameMetadata.objects.filter(is_active=True).values_list(
        'devices',
        'genres',
        'age_rating',
        'club_format',
    )
    devices = sorted({item for row in metadata_values for item in _split_filter(row[0])})
    genres = sorted({item for row in metadata_values for item in _split_filter(row[1])})
    ages = sorted({row[2] for row in metadata_values if row[2]})

    return render(request, 'catalog/vr_club_games.html', {
        'tariff_packs': tariff_packs,
        'has_vr_club_packs': has_vr_club_packs,
        'games': games,
        'services': services,
        'quiz_form': quiz_form,
        'quiz_sent': quiz_sent,
        'devices': devices,
        'genres': genres,
        'ages': ages,
        'formats': ProductGameMetadata.FORMAT_CHOICES,
        'package_formats': GamePack.FORMAT_CHOICES,
        'selected_filters': request.GET,
    })


@require_POST
def add_vr_club_custom_pack_to_cart_view(request):
    raw_game_ids = request.POST.getlist('game_ids')
    try:
        game_ids = [int(value) for value in raw_game_ids]
    except (TypeError, ValueError):
        game_ids = []
    games = list(
        Product.objects
        .filter(pk__in=game_ids, is_active=True, game_metadata__is_active=True)
        .select_related('game_metadata')
    )
    if not games:
        messages.warning(request, 'Выберите хотя бы одну игру для комплекта.')
        return redirect(f"{reverse('catalog:vr_club_games')}#constructor")

    try:
        service_ids = [int(value) for value in request.POST.getlist('service_ids')]
    except (TypeError, ValueError):
        service_ids = []
    services = list(Service.objects.filter(pk__in=service_ids, is_active=True, is_vr_club_service=True))
    service_snapshots = [{'id': service.pk, 'name': service.name, 'price': float(service.price or 0)} for service in services]
    try:
        headset_count = max(1, int(request.POST.get('headset_count') or 1))
    except (TypeError, ValueError):
        headset_count = 1

    cart_items = list(get_cart_items(request))
    cart_items.append(build_custom_game_pack_item_dict(
        name='Индивидуальный комплект игр для VR-клуба',
        game_ids=[game.pk for game in games],
        games=games,
        services=service_snapshots,
        headset_count=headset_count,
        club_format=(request.POST.get('club_format') or '').strip(),
        devices=(request.POST.get('devices') or '').strip(),
        audience=(request.POST.get('audience') or '').strip(),
    ))
    for service in services:
        cart_items.append(_build_service_item_dict(service, 1))

    if request.user.is_authenticated:
        save_cart_to_db(request, cart_items)
    else:
        save_cart_to_session(request, cart_items)
    return redirect('catalog:cart')
