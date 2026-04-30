from dataclasses import dataclass

from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from ..legal_docs import get_legal_doc


@dataclass(frozen=True)
class _LegalOperatorContacts:
    full_name: str
    short_name: str
    legal_form: str
    inn: str
    ogrn: str
    legal_address: str
    postal_address: str
    email: str
    pd_email: str
    phone: str
    authority_basis: str
    bank_account: str
    bank_name: str
    bank_bik: str
    bank_inn: str
    bank_corr_account: str
    bank_legal_address: str


def _get_legal_operator_contacts():
    return _LegalOperatorContacts(
        full_name=getattr(settings, 'LEGAL_OPERATOR_FULL_NAME', getattr(settings, 'SITE_BRAND', 'BizonVR')),
        short_name=getattr(settings, 'LEGAL_OPERATOR_SHORT_NAME', getattr(settings, 'SITE_BRAND', 'BizonVR')),
        legal_form=getattr(settings, 'LEGAL_OPERATOR_FORM', '[ООО/ИП]'),
        inn=getattr(settings, 'LEGAL_OPERATOR_INN', '[ИНН]'),
        ogrn=getattr(settings, 'LEGAL_OPERATOR_OGRN', '[ОГРН / ОГРНИП]'),
        legal_address=getattr(settings, 'LEGAL_OPERATOR_LEGAL_ADDRESS', '[ЮРИДИЧЕСКИЙ АДРЕС]'),
        postal_address=getattr(settings, 'LEGAL_OPERATOR_POSTAL_ADDRESS', '[ПОЧТОВЫЙ АДРЕС]'),
        email=getattr(settings, 'SITE_CONTACT_EMAIL', 'info@example.com'),
        pd_email=getattr(settings, 'LEGAL_OPERATOR_PD_EMAIL', getattr(settings, 'SITE_CONTACT_EMAIL', 'info@example.com')),
        phone=getattr(settings, 'SITE_CONTACT_PHONE', ''),
        authority_basis=getattr(settings, 'LEGAL_SIGNATORY_BASIS', '[УСТАВ / ДОВЕРЕННОСТЬ №___ ОТ ___]'),
        bank_account=getattr(settings, 'LEGAL_BANK_ACCOUNT', ''),
        bank_name=getattr(settings, 'LEGAL_BANK_NAME', ''),
        bank_bik=getattr(settings, 'LEGAL_BANK_BIK', ''),
        bank_inn=getattr(settings, 'LEGAL_BANK_INN', ''),
        bank_corr_account=getattr(settings, 'LEGAL_BANK_CORR_ACCOUNT', ''),
        bank_legal_address=getattr(settings, 'LEGAL_BANK_LEGAL_ADDRESS', ''),
    )


def _render_legal_page(request, slug):
    legal_doc = get_legal_doc(slug)
    if not legal_doc:
        raise Http404()
    return render(request, legal_doc['template_name'], {
        'legal_doc': legal_doc,
        'operator_contacts': _get_legal_operator_contacts(),
    })


def privacy_view(request):
    """Страница политики конфиденциальности."""
    return _render_legal_page(request, 'privacy')


def oferta_view(request):
    """Страница публичной оферты."""
    return _render_legal_page(request, 'oferta')


def user_agreement_view(request):
    return _render_legal_page(request, 'user_agreement')


def pd_consent_view(request):
    return _render_legal_page(request, 'pd_consent')


def cookies_policy_view(request):
    return _render_legal_page(request, 'cookies_policy')


def sales_terms_view(request):
    return _render_legal_page(request, 'sales_terms')


def service_request_terms_view(request):
    return _render_legal_page(request, 'service_request_terms')
