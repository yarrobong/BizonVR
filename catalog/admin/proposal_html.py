from decimal import Decimal

from django.utils.html import escape

def build_commercial_proposal_html(
    rows,
    total,
    date_display,
    valid_until,
    manager_first_name,
    manager_last_name,
    manager_email,
    manager_phone,
    site_url,
    site_brand,
    logo_url,
    site_phone,
    site_email,
    site_address,
):
    """Собирает HTML-документ коммерческого предложения в стиле kp.html (тёмная тема, неоновые акценты)."""
    def _fmt(val):
        """Форматирование денег: 260000 -> 260 000; 12500.5 -> 12 500,50."""
        try:
            d = Decimal(str(val))
        except Exception:
            d = Decimal('0')
        d = d.quantize(Decimal('0.01'))
        if d == d.to_integral():
            return f'{int(d):,}'.replace(',', ' ')
        # RU-формат: пробелы в тысячах + запятая в дробной части
        return f'{d:,.2f}'.replace(',', ' ').replace('.', ',')

    def _truncate_for_desc(text: str, max_chars: int = 160) -> str:
        """Обрезка описания с добавлением троеточия (для HTML/PDF)."""
        t = (text or '').replace('\n', ' ').replace('\r', ' ').strip()
        t = ' '.join(t.split())
        if len(t) <= max_chars:
            return t
        cut = t[:max_chars].rstrip()
        if cut.endswith(('…', '.', ',', ';', ':')):
            cut = cut.rstrip('. ,;:')
        return cut + '…'

    css = '''
    @page { size: A4; margin: 0; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background-color: #0b0d14;
        display: flex;
        justify-content: center;
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        color: #e5e7eb;
        padding: 18px 0;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
    .a4-page {
        width: 210mm;
        min-height: 297mm;
        background: linear-gradient(180deg, #0b0d14 0%, #151923 100%);
        padding: 14mm 14mm;
        border-radius: 25px;
        position: relative;
        overflow: hidden;
        border: 1px solid rgba(255,255,255,0.12);
        box-shadow:
          0 25px 50px -12px rgba(0,0,0,0.35),
          0 0 0 1px rgba(255,255,255,0.06),
          0 0 40px rgba(0,212,255,0.10);
    }
    .a4-page::before {
        content: '';
        position: absolute;
        top: 0; left: 0; width: 100%; height: 3px;
        background: linear-gradient(90deg, #00D4FF, rgba(188, 19, 254, 0.55), rgba(0,0,0,0));
        box-shadow: 0 0 14px rgba(0, 212, 255, 0.55);
    }
    
    .header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 26px;
        border-bottom: 1px solid rgba(255,255,255,0.10); padding-bottom: 18px; }
    .brand-logo {
        font-size: 34px;
        font-weight: 900;
        color: #ffffff;
        letter-spacing: 1px;
        font-family: "Orbitron", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
        text-shadow: 0 0 14px rgba(0, 212, 255, 0.35);
        margin-bottom: 4px;
    }
    .brand-logo img { max-height: 52px; max-width: 220px; display: block;
        filter: drop-shadow(0 0 10px rgba(0, 212, 255, 0.28)); }
    .brand-subtitle { font-size: 12px; color: rgba(0, 212, 255, 0.92); text-transform: uppercase; letter-spacing: 3px; }
    .contacts { text-align: right; font-size: 12px; line-height: 1.6; color: rgba(229,231,235,0.70); }
    .contacts span { color: rgba(0, 212, 255, 0.95); font-weight: 700; }
    .title-block { text-align: center; margin-bottom: 22px; }
    .title-block h1 { font-size: 26px; text-transform: uppercase; color: #ffffff; margin-bottom: 10px;
        letter-spacing: 2.5px; text-shadow: 0 0 14px rgba(0, 212, 255, 0.35); }
    .title-block p { font-size: 13px; color: rgba(0, 212, 255, 0.85); }
    .info-panel { display: flex; justify-content: space-between;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.10);
        border-left: 3px solid rgba(0, 212, 255, 0.95);
        padding: 14px 16px; margin-bottom: 22px; font-size: 13px;
        border-radius: 25px; }
    .info-panel strong { color: #fff; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 30px; table-layout: fixed; }
    th { background: rgba(255,255,255,0.06); color: #ffffff; text-transform: uppercase; font-size: 11px;
        letter-spacing: 1px; padding: 10px 8px; text-align: left;
        border-bottom: 2px solid rgba(0, 212, 255, 0.55); }
    td { padding: 12px 8px; font-size: 13px; border-bottom: 1px solid rgba(255, 255, 255, 0.05); vertical-align: middle; word-break: break-word; }
    tr:hover td { background: rgba(0, 243, 255, 0.03); }
    .item-photo { width: 60px; height: 60px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
    .item-photo img { width: 60px; height: 60px; object-fit: contain; }
    .col-num { width: 5%; text-align: center; }
    .col-photo { width: 10%; }
    .col-name { width: 15%; font-weight: bold; color: #fff; }
    .col-desc { width: 20%; color: #888; font-size: 10px; line-height: 1.35; }
    .col-desc .desc-clamp {
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        max-height: calc(1.35em * 3);
    }
    .col-qty { width: 10%; text-align: center; }
    .col-price { width: 10%; white-space: nowrap; text-align: right; }
    .col-sum { width: 10%; font-weight: bold; color: rgba(0, 212, 255, 0.95); white-space: nowrap; text-align: right; }
    .footer-block { display: flex; justify-content: flex-end; align-items: center; margin-bottom: 40px; }
    .total-box { background: rgba(0, 212, 255, 0.08); padding: 14px 22px; border-radius: 25px;
        border: 1px solid rgba(0, 212, 255, 0.24); box-shadow: 0 0 20px rgba(0, 212, 255, 0.12); }
    .total-box .total-label { font-size: 13px; color: rgba(229,231,235,0.72); margin-right: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .total-box .total-amount { font-size: 22px; font-weight: 900; color: #ffffff; text-shadow: 0 0 14px rgba(0, 212, 255, 0.28); }
    .date-signature { display: flex; justify-content: space-between; font-size: 12px; color: #666;
        border-top: 1px solid rgba(255,255,255,0.1); padding-top: 20px; }
    .legal-note { margin-top: 14px; font-size: 11px; line-height: 1.45; color: rgba(229,231,235,0.65); }
    @media print {
        body { padding: 0; background-color: #0b0d14; }
        .a4-page { box-shadow: none; margin: 0; border: none; border-radius: 0; }
        tr:hover td { background: transparent; }
    }
    '''
    lines = [
        '<!DOCTYPE html>',
        '<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f'<title>Коммерческое предложение - {escape(site_brand)}</title>',
        '<style>', css.strip(), '</style></head><body>',
        '<div class="a4-page">',
        '<div class="header">',
        '<div>',
    ]
    if logo_url:
        lines.append(f'<div class="brand-logo"><img src="{escape(logo_url)}" alt="" style="max-height: 48px;"></div>')
    else:
        lines.append(f'<div class="brand-logo">{escape(site_brand)}</div>')
    lines.append('<div class="brand-subtitle">Виртуальная реальность</div>')
    lines.append('</div>')
    lines.append('<div class="contacts">')
    if site_phone:
        lines.append(f'<p><span>Тел:</span> {escape(site_phone)}</p>')
    if site_email:
        lines.append(f'<p><span>Email:</span> {escape(site_email)}</p>')
    if site_url:
        lines.append(f'<p><span>Сайт:</span> {escape(site_url)}</p>')
    lines.append('</div></div>')
    lines.append('<div class="title-block">')
    lines.append('<h1>Коммерческое предложение</h1>')
    # Строку про «Официальный документ / Действительно до ...» убрали — срок указан внизу (7 дней).
    lines.append('</div>')
    lines.append('<div class="info-panel">')
    lines.append('<div>')
    manager_full_name = f'{(manager_last_name or "").strip()} {(manager_first_name or "").strip()}'.strip() or '—'
    lines.append(f'Менеджер: <strong>{escape(manager_full_name)}</strong><br>')
    lines.append(f'Телефон для связи: <strong>{escape(manager_phone) or "—"}</strong>')
    lines.append('</div></div>')
    lines.append('<table>')
    lines.append(
        '<thead><tr><th class="col-num">№</th><th class="col-photo">Фото</th><th class="col-name">Название</th>'
        '<th class="col-desc">Описание</th><th class="col-qty">Кол-во</th><th class="col-price">Цена (₽)</th>'
        '<th class="col-sum">Итого (₽)</th></tr></thead><tbody>'
    )
    for r in rows:
        if r.get('image_url'):
            photo_cell = f'<div class="item-photo"><img src="{escape(r["image_url"])}" alt=""></div>'
        else:
            photo_cell = '<div class="item-photo">—</div>'
        desc = escape(_truncate_for_desc(r.get('description') or '', max_chars=160))
        price_fmt = _fmt(r['price'])
        sum_fmt = _fmt(r['row_total'])
        lines.append(
            f'<tr><td class="col-num" style="text-align: center;">{r["num"]}</td>'
            f'<td class="col-photo">{photo_cell}</td>'
            f'<td class="col-name">{escape(r["name"])}</td><td class="col-desc"><div class="desc-clamp">{desc}</div></td>'
            f'<td class="col-qty">{r["qty"]}</td><td class="col-price">{price_fmt} ₽</td>'
            f'<td class="col-sum">{sum_fmt} ₽</td></tr>'
        )
    lines.append('</tbody></table>')
    total_fmt = _fmt(total)
    lines.append(
        '<div class="footer-block">'
        '<div class="total-box">'
        '<span class="total-label">Итого к оплате:</span>'
        f'<span class="total-amount">{total_fmt} ₽</span>'
        '</div></div>'
    )
    lines.append(
        '<div class="date-signature">'
        f'<div>Дата составления: <strong>{escape(date_display)}</strong></div>'
        '</div>'
    )
    lines.append(
        '<div class="legal-note">'
        'Данное коммерческое предложение является официальным и действует в течение 7 дней с даты составления.<br>'
        'Цена не включает в себя доставку. Доставка оплачивается покупателем при получении.'
        '</div>'
    )
    lines.append('</div></body></html>')
    return '\n'.join(lines)
