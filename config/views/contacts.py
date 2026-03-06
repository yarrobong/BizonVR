from django.contrib import messages
from django.shortcuts import redirect, render

from catalog.models import ContactRequest

from ..forms import ContactForm
from ..legal_consent import build_legal_acceptance_payload


def contacts_view(request):
    """Страница контактов: форма обратной связи и контактная информация."""
    form = ContactForm()
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            ContactRequest.objects.create(
                name=form.cleaned_data['name'],
                email=form.cleaned_data['email'],
                phone=form.cleaned_data.get('phone', ''),
                message=form.cleaned_data['message'],
                **build_legal_acceptance_payload(request),
            )
            messages.success(request, 'Спасибо! Ваше сообщение отправлено. Мы свяжемся с вами в ближайшее время.')
            return redirect('contacts')
    return render(request, 'contacts.html', {'form': form})
