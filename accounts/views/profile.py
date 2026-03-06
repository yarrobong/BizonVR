from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def profile_view(request):
    """Личный кабинет: баланс, заказы."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    from ..models import Profile

    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    profile = request.user.profile
    return render(request, 'accounts/profile.html', {
        'user': request.user,
        'profile': profile,
    })


@require_GET
def balance_history_view(request):
    """История операций по балансу."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    from ..models import BalanceTransaction, Profile

    Profile.objects.get_or_create(user=request.user, defaults={'phone': request.user.username})
    transactions = BalanceTransaction.objects.filter(user=request.user)[:100]
    return render(request, 'accounts/balance_history.html', {
        'profile': request.user.profile,
        'user': request.user,
        'transactions': transactions,
    })
