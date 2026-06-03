from django.db import models


class SiteLeadRequest(models.Model):
    SOURCE_CHECKOUT = 'checkout'
    SOURCE_PURCHASE_REQUEST = 'purchase_request'
    SOURCE_CONTACTS = 'contacts'
    SOURCE_CALLBACK_ARENDA = 'callback_arenda'
    SOURCE_CALLBACK_USLUGI = 'callback_uslugi'
    SOURCE_COMPACT_VR = 'compact_vr'
    SOURCE_VR_CLUB = 'vr_club'
    SOURCE_TEST = 'test'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_CHECKOUT, 'Корзина / checkout'),
        (SOURCE_PURCHASE_REQUEST, 'Заявка с карточки товара'),
        (SOURCE_CONTACTS, 'Контакты / обратная связь'),
        (SOURCE_CALLBACK_ARENDA, 'Обратный звонок / аренда'),
        (SOURCE_CALLBACK_USLUGI, 'Заявка на услуги'),
        (SOURCE_COMPACT_VR, 'Compact VR'),
        (SOURCE_VR_CLUB, 'VR-клуб'),
        (SOURCE_TEST, 'Тестовая заявка'),
    ]

    SPAM_STATUS_CLEAN = 'clean'
    SPAM_STATUS_SUSPICIOUS = 'suspicious'
    SPAM_STATUS_SPAM = 'spam'
    SPAM_STATUS_CHOICES = [
        (SPAM_STATUS_CLEAN, 'Чистая'),
        (SPAM_STATUS_SUSPICIOUS, 'Подозрительная'),
        (SPAM_STATUS_SPAM, 'Спам'),
    ]

    SYNC_STATUS_PENDING = 'pending'
    SYNC_STATUS_SYNCED = 'synced'
    SYNC_STATUS_FAILED = 'failed'
    SYNC_STATUS_SKIPPED = 'skipped'
    SYNC_STATUS_CHOICES = [
        (SYNC_STATUS_PENDING, 'Ожидает синка'),
        (SYNC_STATUS_SYNCED, 'Синхронизирована'),
        (SYNC_STATUS_FAILED, 'Ошибка синка'),
        (SYNC_STATUS_SKIPPED, 'Пропущена'),
    ]

    BITRIX_ENTITY_TYPE_DEAL = 'deal'

    source_type = models.CharField('Тип источника', max_length=32, choices=SOURCE_TYPE_CHOICES, db_index=True)
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='site_lead_requests',
        verbose_name='Локальный заказ',
    )
    name = models.CharField('Имя', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=64, blank=True)
    email = models.EmailField('Email', blank=True)
    city = models.CharField('Город', max_length=255, blank=True)
    message = models.TextField('Сообщение', blank=True)
    page_url = models.URLField('URL страницы', blank=True, max_length=500)
    referer = models.URLField('Referer', blank=True, max_length=500)
    utm_source = models.CharField('UTM source', max_length=255, blank=True)
    utm_medium = models.CharField('UTM medium', max_length=255, blank=True)
    utm_campaign = models.CharField('UTM campaign', max_length=255, blank=True)
    utm_content = models.CharField('UTM content', max_length=255, blank=True)
    utm_term = models.CharField('UTM term', max_length=255, blank=True)
    cart_snapshot = models.JSONField('Снимок корзины', default=list, blank=True)
    raw_payload = models.JSONField('Сырой payload', default=dict, blank=True)
    spam_status = models.CharField(
        'Статус антиспама',
        max_length=16,
        choices=SPAM_STATUS_CHOICES,
        default=SPAM_STATUS_CLEAN,
        db_index=True,
    )
    spam_reason = models.TextField('Причина антиспама', blank=True)
    bitrix_entity_type = models.CharField('Тип сущности Bitrix', max_length=32, blank=True)
    bitrix_entity_id = models.CharField('ID сущности Bitrix', max_length=64, blank=True)
    bitrix_contact_id = models.CharField('ID контакта Bitrix', max_length=64, blank=True, db_index=True)
    bitrix_deal_id = models.CharField('ID сделки Bitrix', max_length=64, blank=True, db_index=True)
    bitrix_synced_at = models.DateTimeField('Когда синхронизирована с Bitrix', null=True, blank=True)
    sync_status = models.CharField(
        'Статус синка',
        max_length=16,
        choices=SYNC_STATUS_CHOICES,
        default=SYNC_STATUS_PENDING,
        db_index=True,
    )
    sync_error = models.TextField('Ошибка синка', blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Аудит заявки с сайта'
        verbose_name_plural = 'Аудит заявок с сайта'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.get_source_type_display()} #{self.pk}'
