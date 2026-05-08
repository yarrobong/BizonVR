from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from config.legal_consent import build_legal_acceptance_payload

from ..cart_services import (
    _build_service_item_dict,
    build_custom_game_pack_item_dict,
    get_cart_items,
    save_cart_to_db,
    save_cart_to_session,
)
from ..forms import VRClubQuizForm
from ..models import GamePack, Product, ProductGameMetadata, Service, VRClubQuizRequest


def _split_filter(value):
    return [part.strip() for part in (value or '').split(',') if part.strip()]


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
        qs = qs.filter(game_metadata__devices__icontains=device)
    if genre:
        qs = qs.filter(game_metadata__genres__icontains=genre)
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


def vr_club_games_view(request):
    quiz_sent = False
    quiz_form = VRClubQuizForm()
    if request.method == 'POST':
        quiz_form = VRClubQuizForm(request.POST)
        if quiz_form.is_valid():
            VRClubQuizRequest.objects.create(
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
            quiz_form = VRClubQuizForm()
            quiz_sent = True

    tariff_packs = list(
        GamePack.objects
        .filter(is_active=True, show_on_vr_club_page=True)
        .select_related('category')
        .prefetch_related('entries__product', 'tags')
        .order_by('vr_club_tariff', '-created_at')[:6]
    )
    if not tariff_packs:
        tariff_packs = list(
            GamePack.objects
            .filter(is_active=True)
            .select_related('category')
            .prefetch_related('entries__product', 'tags')
            .order_by('-created_at')[:3]
        )

    games = list(_filter_games(request)[:60])
    services = list(Service.objects.filter(is_active=True, is_vr_club_service=True).order_by('order', 'name'))
    metadata_values = ProductGameMetadata.objects.filter(is_active=True).values_list('devices', 'genres', 'age_rating', 'club_format')
    devices = sorted({item for row in metadata_values for item in _split_filter(row[0])})
    genres = sorted({item for row in metadata_values for item in _split_filter(row[1])})
    ages = sorted({row[2] for row in metadata_values if row[2]})
    formats = ProductGameMetadata.FORMAT_CHOICES

    return render(request, 'catalog/vr_club_games.html', {
        'tariff_packs': tariff_packs,
        'games': games,
        'services': services,
        'quiz_form': quiz_form,
        'quiz_sent': quiz_sent,
        'devices': devices,
        'genres': genres,
        'ages': ages,
        'formats': formats,
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

    service_ids = []
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
