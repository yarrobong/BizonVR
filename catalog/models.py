import html
import re
from decimal import Decimal
from urllib.parse import urlparse

import requests

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from config.formatting import format_currency_amount
from .pricing import (
    PURCHASE_MODE_CHOICES,
    PURCHASE_MODE_STOCK,
    resolve_in_stock_base_price,
    resolve_in_stock_price,
    resolve_on_request_price,
)


class CatalogSection(models.Model):
    """Раздел каталога в меню: Решения для VR бизнеса, VR-аттракционы и т.д."""
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('Slug', max_length=200, unique=True, blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)
    icon = models.TextField(
        'SVG иконка',
        blank=True,
        help_text='SVG код иконки для отображения слева от названия раздела',
    )

    class Meta:
        verbose_name = 'Раздел каталога'
        verbose_name_plural = 'Разделы каталога'
        ordering = ('order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


TILE_SIZE_CHOICES = [
    ('small', 'Маленький квадрат (1×1)'),
    ('medium', 'Широкий (2×1)'),
    ('large', 'Большой квадрат (2×2)'),
    ('tall', 'Высокий (1×2)'),
]


class Category(models.Model):
    """Категория товаров (VR оборудование, VR аттракционы, Трейдин устройства)."""
    section = models.ForeignKey(
        CatalogSection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='categories',
        verbose_name='Раздел каталога',
    )
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('Slug', max_length=200, unique=True, blank=True)
    icon = models.TextField(
        'SVG иконка',
        blank=True,
        help_text='SVG код иконки для отображения слева от названия категории',
    )
    image = models.ImageField(
        'Изображение категории',
        upload_to='categories/',
        blank=True,
        null=True,
        help_text='Показывается в плитках категории. Если не заполнено, используется фото набора или товара.',
    )
    tile_size = models.CharField(
        'Размер плитки в меню',
        max_length=10,
        choices=TILE_SIZE_CHOICES,
        default='small',
    )
    is_bundles_category = models.BooleanField(
        'Показывать наборы товаров',
        default=False,
        help_text='Вместо товаров в этой категории отображаются комплекты (наборы). Добавьте категорию в нужный раздел каталога.',
    )

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ('name',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class ProductTag(models.Model):
    """Тег товара: Бестселлер, Выбор экспертов, Новинка, Акция."""
    name = models.CharField('Название', max_length=100)
    slug = models.SlugField('Slug', max_length=100, unique=True)
    order = models.PositiveIntegerField('Порядок отображения', default=0)

    class Meta:
        verbose_name = 'Тег товара'
        verbose_name_plural = 'Теги товаров'
        ordering = ('order', 'name')

    def __str__(self):
        return self.name


RUTUBE_HOSTS = {'rutube.ru', 'www.rutube.ru', 'm.rutube.ru'}
RUTUBE_PUBLIC_VIDEO_PREFIX = '/video/'
RUTUBE_PRIVATE_VIDEO_PREFIX = '/video/private/'
RUTUBE_REQUEST_TIMEOUT_SECONDS = 4
RUTUBE_REQUEST_HEADERS = {
    'User-Agent': 'BizonVR/1.0 (+https://bizonvr.ru)',
}


def _parse_rutube_video_url(raw_url):
    raw_value = (raw_url or '').strip()
    if not raw_value:
        raise ValidationError({'rutube_url': 'Укажите ссылку на видео RUTUBE.'})

    parsed = urlparse(raw_value)
    if not parsed.scheme:
        parsed = urlparse(f'https://{raw_value}')

    host = (parsed.netloc or '').split(':', 1)[0].lower()
    if host not in RUTUBE_HOSTS:
        raise ValidationError({'rutube_url': 'Допустимы только публичные ссылки RUTUBE.'})

    if parsed.path.startswith(RUTUBE_PRIVATE_VIDEO_PREFIX) or 'p=' in (parsed.query or ''):
        raise ValidationError({'rutube_url': 'Приватные видео RUTUBE и ссылки с ключом доступа не поддерживаются.'})

    path = parsed.path.rstrip('/')
    if not path.startswith(RUTUBE_PUBLIC_VIDEO_PREFIX):
        raise ValidationError({'rutube_url': 'Вставьте обычную публичную ссылку вида https://rutube.ru/video/<id>/.'})

    segments = [segment for segment in path.split('/') if segment]
    if len(segments) < 2 or segments[0] != 'video' or not segments[1]:
        raise ValidationError({'rutube_url': 'Не удалось определить ID видео RUTUBE по ссылке.'})

    video_id = segments[1]
    normalized_url = f'https://rutube.ru/video/{video_id}/'
    embed_url = f'https://rutube.ru/play/embed/{video_id}'
    return normalized_url, video_id, embed_url


def _extract_rutube_embed_src(html_snippet):
    if not html_snippet:
        return ''
    match = re.search(r'src=["\']([^"\']+)["\']', html_snippet, re.IGNORECASE)
    return html.unescape(match.group(1).strip()) if match else ''


def _extract_meta_content(page_html, meta_names):
    for meta_name in meta_names:
        patterns = (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(meta_name)}["\']',
        )
        for pattern in patterns:
            match = re.search(pattern, page_html, re.IGNORECASE)
            if match:
                return html.unescape(match.group(1).strip())
    return ''


def _fetch_rutube_video_metadata(normalized_url, fallback_embed_url):
    try:
        response = requests.get(
            'https://rutube.ru/api/oembed/',
            params={'url': normalized_url, 'format': 'json'},
            timeout=RUTUBE_REQUEST_TIMEOUT_SECONDS,
            headers=RUTUBE_REQUEST_HEADERS,
        )
        response.raise_for_status()
        data = response.json() or {}
        embed_url = _extract_rutube_embed_src(data.get('html', '')) or fallback_embed_url
        return {
            'embed_url': embed_url,
            'thumbnail_url': (data.get('thumbnail_url') or '').strip(),
            'title': (data.get('title') or '').strip(),
        }
    except (requests.RequestException, ValueError, TypeError):
        pass

    try:
        response = requests.get(
            normalized_url,
            timeout=RUTUBE_REQUEST_TIMEOUT_SECONDS,
            headers=RUTUBE_REQUEST_HEADERS,
        )
        response.raise_for_status()
    except requests.RequestException:
        return {}

    page_html = response.text or ''
    return {
        'embed_url': (
            _extract_meta_content(page_html, ('og:video:iframe', 'twitter:player'))
            or fallback_embed_url
        ),
        'thumbnail_url': _extract_meta_content(
            page_html,
            ('og:image:url', 'og:image', 'twitter:image', 'thumbnailUrl'),
        ),
        'title': _extract_meta_content(page_html, ('og:title', 'twitter:title')),
    }


class Product(models.Model):
    """Товар в каталоге."""
    PRODUCT_KIND_PHYSICAL = 'physical'
    PRODUCT_KIND_GAME_PACK = 'game_pack'
    PRODUCT_KIND_CHOICES = [
        (PRODUCT_KIND_PHYSICAL, 'Обычный товар'),
        (PRODUCT_KIND_GAME_PACK, 'Пак игр'),
    ]

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='products',
        verbose_name='Категория',
    )
    name = models.CharField('Название', max_length=300)
    sku = models.CharField(
        'SKU',
        max_length=64,
        blank=True,
        db_index=True,
        help_text='Используется только для товаров без вариантов. Для variant-first товаров задавайте SKU на уровне варианта.',
    )
    slug = models.SlugField('Slug', max_length=300, unique=True, blank=True)
    description = models.TextField('Описание', blank=True)
    product_kind = models.CharField(
        'Тип товара',
        max_length=20,
        choices=PRODUCT_KIND_CHOICES,
        default=PRODUCT_KIND_PHYSICAL,
        db_index=True,
        help_text='Пак игр не использует складские остатки и продаётся как одна позиция.',
    )
    price = models.DecimalField('Цена из наличия', max_digits=12, decimal_places=2, null=True, blank=True)
    discount_percent = models.DecimalField(
        'Скидка, %',
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Скидка применяется к цене из наличия товара и его вариантов.',
    )
    price_on_request = models.DecimalField(
        'Цена под заказ',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Более низкая цена для покупки под заказ. Если не заполнена, на витрине остаётся только цена из наличия.',
    )
    image = models.ImageField('Изображение', upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField('Активен', default=True)
    allow_order_on_request = models.BooleanField(
        'Доступен под заказ',
        default=True,
        help_text='Если товара нет в наличии, покупатель может оформить заказ под заказ',
    )
    avito_url = models.URLField(
        'Ссылка на Avito',
        max_length=500,
        blank=True,
        default='',
        help_text='Прямая ссылка на этот же товар в Avito.',
    )
    ozon_url = models.URLField(
        'Ссылка на Ozon',
        max_length=500,
        blank=True,
        default='',
        help_text='Прямая ссылка на этот же товар в Ozon.',
    )
    wildberries_url = models.URLField(
        'Ссылка на Wildberries',
        max_length=500,
        blank=True,
        default='',
        help_text='Прямая ссылка на этот же товар в Wildberries.',
    )
    tags = models.ManyToManyField(
        ProductTag,
        related_name='products',
        verbose_name='Теги',
        blank=True,
        help_text='Бестселлер, Выбор экспертов, Новинка, Акция',
    )
    option_label = models.CharField(
        'Подпись к вариантам',
        max_length=100,
        blank=True,
        help_text='Например: Цвет, Размер, Модель. Показывается над выбором варианта.',
    )
    views_count = models.PositiveIntegerField(
        'Просмотры',
        default=0,
        help_text='Счётчик просмотров страницы товара для сортировки по популярности',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ('-created_at',)
        permissions = (
            ('can_restore_backup', 'Can restore catalog backup'),
            ('can_import_catalog_json', 'Can import catalog from JSON'),
        )

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True)
            self.slug = base
            n = 1
            while Product.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{base}-{n}'
                n += 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalog:product_detail', kwargs={'slug': self.slug})

    def get_display_image(self):
        """Первое доступное изображение: основное, затем вариант, затем доп. фото. Для карточки товара."""
        if self.image:
            return self.image
        for v in self.variants.all():
            if v.image:
                return v.image
        first_extra = self.images.order_by('order', 'id').first()
        if first_extra and first_extra.image:
            return first_extra.image
        return None

    @property
    def in_stock_price(self):
        return resolve_in_stock_price(self)

    @property
    def on_request_price(self):
        return resolve_on_request_price(self)

    @property
    def has_on_request_price(self):
        return self.on_request_price is not None

    @property
    def is_game_pack(self):
        return self.product_kind == self.PRODUCT_KIND_GAME_PACK

    @property
    def is_game_product(self):
        if self.is_game_pack:
            return True
        try:
            return bool(self.game_metadata.is_active)
        except ObjectDoesNotExist:
            return False

    @property
    def tracks_stock(self):
        return not self.is_game_product

class ProductVariant(models.Model):
    """Вариант товара: цвет, размер, модель и т.п. Своё фото и цена (опционально)."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        verbose_name='Товар',
    )
    name = models.CharField('Название', max_length=100)
    sku = models.CharField('SKU', max_length=64, blank=True, db_index=True)
    image = models.ImageField('Изображение', upload_to='products/', blank=True, null=True)
    price_override = models.DecimalField(
        'Цена из наличия (переопределение)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Пусто — использовать цену из наличия у товара.',
    )
    price_on_request_override = models.DecimalField(
        'Цена под заказ (переопределение)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Пусто — использовать цену под заказ у товара.',
    )
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Вариант товара'
        verbose_name_plural = 'Варианты товара'
        ordering = ('order', 'name')

    def __str__(self):
        return f'{self.product.name} — {self.name}'

    @property
    def price(self):
        return self.price_override if self.price_override is not None else self.product.price

    @property
    def in_stock_price(self):
        return resolve_in_stock_price(self.product, self)

    @property
    def on_request_price(self):
        return resolve_on_request_price(self.product, self)

    @property
    def has_on_request_price(self):
        return self.on_request_price is not None


class ProductVariantCharacteristic(models.Model):
    """Характеристика варианта товара (наследуется от товара, можно редактировать)."""
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='characteristics',
        verbose_name='Вариант',
    )
    name = models.CharField('Название', max_length=200)
    value = models.CharField('Значение', max_length=500)

    class Meta:
        verbose_name = 'Характеристика варианта'
        verbose_name_plural = 'Характеристики варианта'
        ordering = ('name',)

    def __str__(self):
        return f'{self.name}: {self.value}'


class ProductImage(models.Model):
    """Дополнительное фото товара для галереи."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Товар',
    )
    image = models.ImageField('Изображение', upload_to='products/')
    order = models.PositiveIntegerField('Порядок', default=0, db_index=True)

    class Meta:
        verbose_name = 'Фото товара'
        verbose_name_plural = 'Фото товара'
        ordering = ('order', 'id')

    def __str__(self):
        return f'{self.product.name} — фото #{self.order}'


class ProductVideo(models.Model):
    """Видео товара из RUTUBE для галереи карточки."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='videos',
        verbose_name='Товар',
    )
    rutube_url = models.URLField(
        'Ссылка RUTUBE',
        max_length=500,
        help_text='Вставьте обычную публичную ссылку на видео RUTUBE.',
    )
    rutube_video_id = models.CharField('ID видео RUTUBE', max_length=100, blank=True, db_index=True)
    embed_url = models.URLField('Embed URL', max_length=500, blank=True)
    thumbnail_url = models.URLField('Постер', max_length=500, blank=True)
    title = models.CharField('Заголовок видео', max_length=500, blank=True)
    order = models.PositiveIntegerField('Порядок', default=0, db_index=True)

    class Meta:
        verbose_name = 'Видео товара'
        verbose_name_plural = 'Видео товара'
        ordering = ('order', 'id')

    def __str__(self):
        label = self.title or self.rutube_video_id or 'видео'
        return f'{self.product.name} — {label}'

    def clean(self):
        super().clean()
        normalized_url, video_id, embed_url = _parse_rutube_video_url(self.rutube_url)
        self.rutube_url = normalized_url
        self.rutube_video_id = video_id
        self.embed_url = embed_url

    def save(self, *args, **kwargs):
        previous_video_id = None
        if self.pk:
            previous_video_id = (
                type(self).objects.filter(pk=self.pk).values_list('rutube_video_id', flat=True).first()
            )

        self.clean()

        if previous_video_id and previous_video_id != self.rutube_video_id:
            self.thumbnail_url = ''
            self.title = ''

        metadata = _fetch_rutube_video_metadata(self.rutube_url, self.embed_url)
        if metadata.get('embed_url'):
            self.embed_url = metadata['embed_url']
        if metadata.get('thumbnail_url'):
            self.thumbnail_url = metadata['thumbnail_url']
        if metadata.get('title'):
            self.title = metadata['title']

        super().save(*args, **kwargs)


class ProductContentBlock(models.Model):
    """Управляемые блоки подробного описания на странице товара."""

    class BlockType(models.TextChoices):
        TEXT = 'text', 'Текстовый блок'
        IMAGE_TEXT = 'image_text', 'Картинка и текст'
        FULL_IMAGE = 'full_image', 'Большое изображение'
        VIDEO = 'video', 'Видео'

    class ImagePosition(models.TextChoices):
        LEFT = 'left', 'Слева'
        RIGHT = 'right', 'Справа'

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='content_blocks',
        verbose_name='Товар',
    )
    block_type = models.CharField(
        'Тип блока',
        max_length=20,
        choices=BlockType.choices,
        default=BlockType.TEXT,
    )
    title = models.CharField(
        'Заголовок',
        max_length=255,
        blank=True,
        help_text='Крупный заголовок секции. Для full_image можно оставить пустым.',
    )
    text = models.TextField(
        'Текст',
        blank=True,
        help_text='Основной текст блока. Для full_image не используется.',
    )
    image = models.ImageField(
        'Изображение',
        upload_to='products/content_blocks/',
        blank=True,
        null=True,
        help_text='Изображение для блока. Обязательно для типов "Картинка и текст" и "Большое изображение".',
    )
    image_position = models.CharField(
        'Положение изображения',
        max_length=10,
        choices=ImagePosition.choices,
        default=ImagePosition.LEFT,
        blank=True,
        help_text='Используется только для блока "Картинка и текст".',
    )
    caption = models.CharField(
        'Подпись к изображению',
        max_length=255,
        blank=True,
        help_text='Необязательная подпись под большим изображением.',
    )
    rutube_url = models.URLField(
        'Ссылка RUTUBE',
        max_length=500,
        blank=True,
        help_text='Для видео-блока вставьте обычную публичную ссылку RUTUBE.',
    )
    rutube_video_id = models.CharField('ID видео RUTUBE', max_length=100, blank=True, db_index=True)
    embed_url = models.URLField('Embed URL', max_length=500, blank=True)
    sort_order = models.IntegerField(
        'Порядок',
        default=0,
        db_index=True,
        help_text='Чем меньше число, тем выше блок на странице.',
    )
    is_active = models.BooleanField(
        'Активен',
        default=True,
        help_text='Позволяет временно скрыть блок без удаления.',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Блок подробного описания'
        verbose_name_plural = 'Блоки подробного описания'
        ordering = ('sort_order', 'id')

    def __str__(self):
        label = self.title or self.get_block_type_display()
        return f'{self.product.name} — {label}'

    def clean(self):
        errors = {}

        if self.block_type == self.BlockType.TEXT:
            if not (self.title or '').strip():
                errors['title'] = 'Укажите заголовок для текстового блока.'
            if not (self.text or '').strip():
                errors['text'] = 'Укажите текст для текстового блока.'
        elif self.block_type == self.BlockType.IMAGE_TEXT:
            if not (self.title or '').strip():
                errors['title'] = 'Укажите заголовок для блока "Картинка и текст".'
            if not (self.text or '').strip():
                errors['text'] = 'Укажите текст для блока "Картинка и текст".'
            if not self.image:
                errors['image'] = 'Загрузите изображение для блока "Картинка и текст".'
            if not (self.image_position or '').strip():
                errors['image_position'] = 'Выберите положение изображения.'
        elif self.block_type == self.BlockType.FULL_IMAGE:
            if not self.image:
                errors['image'] = 'Загрузите изображение для блока "Большое изображение".'
        elif self.block_type == self.BlockType.VIDEO:
            if not (self.rutube_url or '').strip():
                errors['rutube_url'] = 'Укажите публичную ссылку RUTUBE для блока "Видео".'
            else:
                try:
                    normalized_url, video_id, embed_url = _parse_rutube_video_url(self.rutube_url)
                except ValidationError as exc:
                    errors.update(exc.message_dict)
                else:
                    self.rutube_url = normalized_url
                    self.rutube_video_id = video_id
                    self.embed_url = embed_url

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.block_type == self.BlockType.VIDEO and self.rutube_url and self.embed_url:
            metadata = _fetch_rutube_video_metadata(self.rutube_url, self.embed_url)
            if metadata.get('embed_url'):
                self.embed_url = metadata['embed_url']

        super().save(*args, **kwargs)


class DescriptionBlockType(models.Model):
    """Справочник типов блоков нового конструктора подробного описания."""

    slug = models.SlugField('Slug', max_length=80, unique=True)
    name = models.CharField('Название', max_length=160)
    description = models.TextField('Описание', blank=True)
    category = models.CharField('Категория', max_length=80, blank=True)
    icon = models.CharField('Иконка', max_length=80, blank=True)
    schema = models.JSONField('Схема данных', default=dict, blank=True)
    default_data = models.JSONField('Данные по умолчанию', default=dict, blank=True)
    preview_data = models.JSONField('Данные для предпросмотра', default=dict, blank=True)
    is_active = models.BooleanField('Активен', default=True)
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)

    class Meta:
        verbose_name = 'Тип блока описания'
        verbose_name_plural = 'Типы блоков описания'
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name


class DescriptionTemplate(models.Model):
    """Готовый шаблон подробного описания товара."""

    name = models.CharField('Название', max_length=180)
    slug = models.SlugField('Slug', max_length=120, unique=True)
    description = models.TextField('Описание', blank=True)
    preview_image = models.ImageField(
        'Изображение предпросмотра',
        upload_to='products/description_templates/',
        blank=True,
        null=True,
    )
    preview_data = models.JSONField('Данные предпросмотра', default=dict, blank=True)
    category = models.CharField('Категория', max_length=120, blank=True)
    is_active = models.BooleanField('Активен', default=True)
    version = models.PositiveIntegerField('Версия', default=1)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Шаблон подробного описания'
        verbose_name_plural = 'Шаблоны подробного описания'
        ordering = ('category', 'name')

    def __str__(self):
        return self.name


class DescriptionTemplateSlot(models.Model):
    """Слот блока внутри шаблона подробного описания."""

    template = models.ForeignKey(
        DescriptionTemplate,
        on_delete=models.CASCADE,
        related_name='slots',
        verbose_name='Шаблон',
    )
    slot_key = models.SlugField('Ключ слота', max_length=80)
    block_type = models.ForeignKey(
        DescriptionBlockType,
        on_delete=models.PROTECT,
        related_name='template_slots',
        verbose_name='Тип блока',
    )
    label = models.CharField('Название блока', max_length=160)
    help_text = models.TextField('Подсказка', blank=True)
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)
    is_required = models.BooleanField('Обязательный', default=False)
    default_data = models.JSONField('Данные по умолчанию', default=dict, blank=True)
    settings = models.JSONField('Настройки редактора', default=dict, blank=True)

    class Meta:
        verbose_name = 'Блок шаблона описания'
        verbose_name_plural = 'Блоки шаблонов описания'
        ordering = ('sort_order', 'id')
        constraints = [
            models.UniqueConstraint(fields=('template', 'slot_key'), name='description_template_slot_key_unique'),
        ]
        indexes = [
            models.Index(fields=('template', 'sort_order'), name='desc_tpl_slot_order_idx'),
        ]

    def __str__(self):
        return f'{self.template.name} — {self.label}'


class ProductDescription(models.Model):
    """Экземпляр нового подробного описания конкретного товара."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Черновик'
        PUBLISHED = 'published', 'Опубликовано'

    class Source(models.TextChoices):
        LEGACY = 'legacy', 'Legacy-блоки'
        TEMPLATE = 'template', 'Шаблон'
        CUSTOM = 'custom', 'Произвольное'

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='product_description',
        verbose_name='Товар',
    )
    template = models.ForeignKey(
        DescriptionTemplate,
        on_delete=models.SET_NULL,
        related_name='product_descriptions',
        verbose_name='Шаблон',
        blank=True,
        null=True,
    )
    title = models.CharField('Заголовок описания', max_length=255, blank=True)
    intro = models.TextField('Вступление', blank=True)
    status = models.CharField('Статус', max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_active = models.BooleanField('Показывать на витрине', default=False)
    source = models.CharField('Источник', max_length=20, choices=Source.choices, default=Source.CUSTOM, db_index=True)
    published_at = models.DateTimeField('Опубликовано', blank=True, null=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Подробное описание товара'
        verbose_name_plural = 'Подробные описания товаров'
        ordering = ('product__name',)
        indexes = [
            models.Index(fields=('status', 'is_active'), name='product_desc_status_active_idx'),
        ]

    def __str__(self):
        return f'{self.product.name} — подробное описание'

    def save(self, *args, **kwargs):
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            from django.utils import timezone

            self.published_at = timezone.now()
        super().save(*args, **kwargs)


class ProductDescriptionBlock(models.Model):
    """Заполненный блок нового подробного описания."""

    description = models.ForeignKey(
        ProductDescription,
        on_delete=models.CASCADE,
        related_name='blocks',
        verbose_name='Описание',
    )
    slot_key = models.SlugField('Ключ слота', max_length=80)
    block_type = models.ForeignKey(
        DescriptionBlockType,
        on_delete=models.PROTECT,
        related_name='product_blocks',
        verbose_name='Тип блока',
    )
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)
    is_active = models.BooleanField('Активен', default=True)
    data = models.JSONField('Данные блока', default=dict, blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Блок подробного описания товара'
        verbose_name_plural = 'Блоки подробных описаний товаров'
        ordering = ('sort_order', 'id')
        constraints = [
            models.UniqueConstraint(fields=('description', 'slot_key'), name='product_description_slot_key_unique'),
        ]
        indexes = [
            models.Index(fields=('description', 'sort_order'), name='prod_desc_block_order_idx'),
        ]

    def __str__(self):
        return f'{self.description.product.name} — {self.slot_key}'

    def clean(self):
        super().clean()
        if not isinstance(self.data, dict):
            raise ValidationError({'data': 'Данные блока должны быть JSON-объектом.'})

        if self.block_type_id and self.block_type.slug == 'video':
            rutube_url = (self.data.get('rutube_url') or '').strip()
            if not rutube_url:
                return
            try:
                normalized_url, video_id, embed_url = _parse_rutube_video_url(rutube_url)
            except ValidationError as exc:
                raise ValidationError({'data': '; '.join(sum(exc.message_dict.values(), []))}) from exc
            self.data = {
                **self.data,
                'rutube_url': normalized_url,
                'rutube_video_id': video_id,
                'embed_url': embed_url,
            }

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ProductDescriptionAsset(models.Model):
    """Медиа-файл, используемый в новом подробном описании."""

    description = models.ForeignKey(
        ProductDescription,
        on_delete=models.CASCADE,
        related_name='assets',
        verbose_name='Описание',
    )
    block = models.ForeignKey(
        ProductDescriptionBlock,
        on_delete=models.CASCADE,
        related_name='assets',
        verbose_name='Блок',
        blank=True,
        null=True,
    )
    image = models.ImageField('Изображение', upload_to='products/description_assets/')
    alt = models.CharField('Alt-текст', max_length=255, blank=True)
    caption = models.CharField('Подпись', max_length=255, blank=True)
    role = models.CharField('Роль', max_length=80, blank=True)
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)

    class Meta:
        verbose_name = 'Медиа подробного описания'
        verbose_name_plural = 'Медиа подробных описаний'
        ordering = ('sort_order', 'id')

    def __str__(self):
        return self.alt or self.caption or f'Медиа #{self.pk}'


class ProductCharacteristic(models.Model):
    """Характеристика товара (название — значение)."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='characteristics',
        verbose_name='Товар',
    )
    name = models.CharField('Название', max_length=200)
    value = models.CharField('Значение', max_length=500)

    class Meta:
        verbose_name = 'Характеристика'
        verbose_name_plural = 'Характеристики'
        ordering = ('name',)

    def __str__(self):
        return f'{self.name}: {self.value}'


class CharacteristicDefinition(models.Model):
    """Управляемая характеристика каталога, связанная с raw ProductCharacteristic.name."""

    class SortingMode(models.TextChoices):
        ALPHA = 'alpha', 'Алфавит'
        NUMERIC_UNIT = 'numeric_unit', 'Число + единица (ГБ, Гц…)'
        SCREEN_SIZE = 'screen_size', 'Диагональ (дюймы)'
        BOOLEAN = 'boolean', 'Да / Нет'
        RESOLUTION = 'resolution', 'Разрешение (WxH)'

    code = models.SlugField('Код', max_length=100, unique=True, blank=True)
    name = models.CharField('Название', max_length=200)
    source_name = models.CharField(
        'Исходное имя характеристики',
        max_length=200,
        unique=True,
        help_text='Точное значение ProductCharacteristic.name, из которого собираются данные фильтра.',
    )
    sorting_mode = models.CharField(
        'Сортировка значений',
        max_length=50,
        choices=SortingMode.choices,
        default=SortingMode.ALPHA,
    )
    is_filterable = models.BooleanField('Использовать в фильтрах', default=True)
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)
    is_active = models.BooleanField('Активна', default=True, db_index=True)

    class Meta:
        verbose_name = 'Определение характеристики'
        verbose_name_plural = 'Определения характеристик'
        ordering = ('sort_order', 'name', 'code')

    def __str__(self):
        return f'{self.name} ({self.code})'

    def save(self, *args, **kwargs):
        if not self.code and self.source_name:
            from .characteristic_codes import generate_unique_characteristic_code

            self.code = generate_unique_characteristic_code(self.source_name, exclude_pk=self.pk)
        super().save(*args, **kwargs)


class CharacteristicSourceAlias(models.Model):
    """Дополнительные raw source names, которые относятся к одной definition."""

    characteristic_definition = models.ForeignKey(
        CharacteristicDefinition,
        on_delete=models.CASCADE,
        related_name='source_aliases',
        verbose_name='Характеристика',
    )
    raw_source_name = models.CharField('Сырое имя характеристики', max_length=200)
    sort_order = models.IntegerField('Порядок', default=0)
    is_active = models.BooleanField('Активен', default=True, db_index=True)

    class Meta:
        verbose_name = 'Алиас source name'
        verbose_name_plural = 'Алиасы source name'
        ordering = ('characteristic_definition', 'sort_order', 'raw_source_name')
        constraints = [
            models.UniqueConstraint(
                fields=['characteristic_definition', 'raw_source_name'],
                name='catalog_char_source_alias_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['characteristic_definition', 'is_active'],
                name='catalog_char_src_active_idx',
            ),
        ]

    def __str__(self):
        return f'{self.characteristic_definition.code}: {self.raw_source_name}'


class CharacteristicValueAlias(models.Model):
    """Нормализация raw значений характеристики для фильтров каталога."""

    characteristic_definition = models.ForeignKey(
        CharacteristicDefinition,
        on_delete=models.CASCADE,
        related_name='value_aliases',
        verbose_name='Характеристика',
    )
    raw_value = models.CharField('Сырое значение', max_length=500)
    normalized_value = models.CharField('Нормализованное значение', max_length=500)
    display_value = models.CharField('Отображаемое значение', max_length=500, blank=True)
    sort_order = models.IntegerField('Порядок', default=0)
    is_active = models.BooleanField('Активен', default=True, db_index=True)

    class Meta:
        verbose_name = 'Алиас значения характеристики'
        verbose_name_plural = 'Алиасы значений характеристик'
        ordering = ('characteristic_definition', 'sort_order', 'raw_value')
        constraints = [
            models.UniqueConstraint(
                fields=['characteristic_definition', 'raw_value'],
                name='catalog_char_value_alias_unique',
            ),
        ]
        indexes = [
            models.Index(
                fields=['characteristic_definition', 'is_active'],
                name='catalog_char_val_active_idx',
            ),
        ]

    def __str__(self):
        return f'{self.characteristic_definition.code}: {self.raw_value} -> {self.normalized_value}'


class FilterConfig(models.Model):
    """Настройка фильтров для категории или раздела.

    Ровно одно из полей category / section должно быть заполнено.
    Если для категории нет конфигов — используются конфиги раздела.
    Если нет ни тех ни других — показываются все активные фильтры (legacy-режим).
    """

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='filter_configs',
        null=True,
        blank=True,
        verbose_name='Категория',
    )
    section = models.ForeignKey(
        CatalogSection,
        on_delete=models.CASCADE,
        related_name='filter_configs',
        null=True,
        blank=True,
        verbose_name='Раздел',
    )
    characteristic_definition = models.ForeignKey(
        CharacteristicDefinition,
        on_delete=models.CASCADE,
        related_name='filter_configs',
        verbose_name='Характеристика',
    )
    is_visible = models.BooleanField('Показывать', default=True, db_index=True)
    is_quick_filter = models.BooleanField('Быстрый фильтр', default=False)
    sort_order = models.IntegerField('Порядок', default=0, db_index=True)
    is_expanded_by_default = models.BooleanField('Раскрыт по умолчанию', default=False)
    show_top_n = models.PositiveIntegerField('Показывать первых N значений', null=True, blank=True)
    hide_single_value = models.BooleanField('Скрывать при одном значении', default=True)

    class Meta:
        verbose_name = 'Конфиг фильтра'
        verbose_name_plural = 'Конфиги фильтров'
        ordering = ('sort_order', 'characteristic_definition__sort_order', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['category', 'characteristic_definition'],
                condition=models.Q(category__isnull=False),
                name='catalog_filter_config_category_def_unique',
            ),
            models.UniqueConstraint(
                fields=['section', 'characteristic_definition'],
                condition=models.Q(section__isnull=False),
                name='catalog_filter_config_section_def_unique',
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.category_id and self.section_id:
            raise ValidationError('Нельзя указать одновременно категорию и раздел.')
        if not self.category_id and not self.section_id:
            raise ValidationError('Необходимо указать категорию или раздел.')

    def __str__(self):
        if self.category_id:
            return f'{self.category.name}: {self.characteristic_definition.name}'
        return f'{self.section.name}: {self.characteristic_definition.name}'


class ProductBundle(models.Model):
    """Набор товаров со своей страницей (описание, изображение) и составом через ProductBundleItem."""
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='product_bundles',
        verbose_name='Категория набора',
        limit_choices_to={'is_bundles_category': True},
    )
    name = models.CharField(
        'Название набора',
        max_length=200,
        blank=True,
        help_text='Отображается на странице набора и в каталоге',
    )
    slug = models.SlugField(
        'Slug',
        max_length=200,
        unique=True,
        blank=True,
        help_text='URL страницы набора, например nabor-quest-3',
    )
    description = models.TextField(
        'Описание',
        blank=True,
        help_text='Как у обычного товара: текст о наборе',
    )
    image = models.ImageField(
        'Изображение',
        upload_to='bundles/',
        blank=True,
        null=True,
        help_text='Главное фото набора (если пусто — используется фото первого товара)',
    )
    views_count = models.PositiveIntegerField(
        'Просмотры',
        default=0,
        help_text='Счётчик просмотров страницы набора для сортировки по популярности',
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Набор товаров'
        verbose_name_plural = 'Наборы товаров'

    def __str__(self):
        return self.name or f'Набор #{self.pk}'

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.category_id and not getattr(self.category, 'is_bundles_category', False):
            raise ValidationError({'category': 'Для набора можно выбрать только bundle-категорию.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name or '', allow_unicode=True) or f'bundle-{self.pk or 0}'
            self.slug = base
            n = 1
            while ProductBundle.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{base}-{n}'
                n += 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalog:bundle_detail', kwargs={'slug': self.slug})

    def get_display_image(self):
        """Главное фото набора, а если его нет — фото первого товара из состава."""
        if self.image:
            return self.image
        for item in self.items.all():
            if item.product.image:
                return item.product.image
        return None

    @property
    def total_price(self):
        """Сумма актуальных цен всех позиций набора."""
        total = sum(float(i.effective_price) * i.quantity for i in self.items.all())
        return total

    @property
    def total_price_without_discount(self):
        """Сумма по базовым ценам товаров без товарных скидок."""
        total = sum(float(resolve_in_stock_base_price(i.product) or 0) * i.quantity for i in self.items.all())
        return total


class ProductBundleItem(models.Model):
    """Позиция в наборе: товар, количество и цена в наборе."""
    bundle = models.ForeignKey(
        ProductBundle,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Набор',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='bundle_items',
        limit_choices_to={'is_active': True},
        verbose_name='Товар',
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    price = models.DecimalField(
        'Цена в наборе (₽)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Рассчитывается автоматически по актуальной цене товара из наличия.',
    )

    class Meta:
        verbose_name = 'Позиция набора'
        verbose_name_plural = 'Позиции набора'
        ordering = ('bundle', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['bundle', 'product'],
                name='catalog_bundleitem_bundle_product_unique',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.product_id:
            base_price = resolve_in_stock_price(self.product)
            if base_price is not None:
                self.price = Decimal(str(base_price)).quantize(Decimal('0.01'))
            else:
                self.price = None
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        """Актуальная цена за единицу в составе набора."""
        if self.product_id:
            base_price = resolve_in_stock_price(self.product)
            if base_price is not None:
                return Decimal(str(base_price)).quantize(Decimal('0.01'))
        return Decimal('0')

    @property
    def regular_price(self):
        """Базовая цена за единицу до товарной скидки."""
        if self.product_id:
            base_price = resolve_in_stock_base_price(self.product)
            if base_price is not None:
                return Decimal(str(base_price)).quantize(Decimal('0.01'))
        return Decimal('0')

    def __str__(self):
        return f'{self.product.name} × {self.quantity} — {format_currency_amount(self.effective_price)}'

class GamePack(models.Model):
    """Standalone catalog entity for a game pack."""

    TARIFF_NONE = ''
    TARIFF_START = 'start'
    TARIFF_CLUB = 'club'
    TARIFF_MAXIMUM = 'maximum'
    TARIFF_CUSTOM = 'custom'
    TARIFF_CHOICES = [
        (TARIFF_NONE, 'Не тариф'),
        (TARIFF_START, 'Старт'),
        (TARIFF_CLUB, 'Клуб'),
        (TARIFF_MAXIMUM, 'Максимум'),
        (TARIFF_CUSTOM, 'Индивидуальный'),
    ]

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='game_packs',
        verbose_name='Игровой раздел',
    )
    name = models.CharField('Название пака', max_length=300)
    slug = models.SlugField('Slug', max_length=300, unique=True, blank=True)
    description = models.TextField('Описание', blank=True)
    image = models.ImageField('Изображение', upload_to='game_packs/', blank=True, null=True)
    price = models.DecimalField('Цена из наличия', max_digits=12, decimal_places=2, null=True, blank=True)
    discount_percent = models.DecimalField(
        'Скидка, %',
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    price_on_request = models.DecimalField('Цена под заказ', max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField('Активен', default=True)
    allow_order_on_request = models.BooleanField('Разрешён заказ под запрос', default=True)
    vr_club_tariff = models.CharField(
        'Тариф для VR-клубов',
        max_length=20,
        choices=TARIFF_CHOICES,
        default=TARIFF_NONE,
        blank=True,
        db_index=True,
    )
    show_on_vr_club_page = models.BooleanField(
        'Показывать в разделе VR-клубов',
        default=False,
        db_index=True,
    )
    club_format = models.CharField('Формат клуба', max_length=120, blank=True)
    devices = models.CharField('Устройства', max_length=255, blank=True, help_text='Через запятую: Quest, Pico, PCVR')
    genres = models.CharField('Жанры', max_length=255, blank=True, help_text='Через запятую')
    age_rating = models.CharField('Возраст', max_length=40, blank=True)
    players_count = models.PositiveIntegerField('Игроков до', null=True, blank=True)
    play_places_count = models.PositiveIntegerField('Игровых мест', null=True, blank=True)
    commercial_pitch = models.TextField('Коммерческий тезис', blank=True)
    included_summary = models.TextField('Что входит', blank=True)
    tags = models.ManyToManyField(ProductTag, related_name='game_packs', verbose_name='Теги', blank=True)
    views_count = models.PositiveIntegerField('Просмотры', default=0)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Игровой пак'
        verbose_name_plural = 'Игровые паки'
        ordering = ('-created_at',)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name, allow_unicode=True)
            self.slug = base
            suffix = 1
            while GamePack.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f'{base}-{suffix}'
                suffix += 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('catalog:game_pack_detail', kwargs={'slug': self.slug})

    def get_display_image(self):
        if self.image:
            return self.image
        for entry in self.entries.select_related('product').all():
            if not entry.product_id:
                continue
            image = entry.product.get_display_image()
            if image:
                return image
        return None

    def get_in_stock_base_price(self):
        total = Decimal('0')
        has_priced_items = False

        for entry in self.entries.select_related('product').all():
            if not entry.product_id:
                continue
            price = resolve_in_stock_price(entry.product)
            if price is None:
                continue
            total += Decimal(str(price)) * entry.quantity
            has_priced_items = True

        for entry in self.service_entries.select_related('service').all():
            price = entry.effective_price
            if price is None:
                continue
            total += Decimal(str(price)) * entry.quantity
            has_priced_items = True

        if has_priced_items:
            return total.quantize(Decimal('0.01'))
        return self.price

    @property
    def in_stock_price(self):
        return resolve_in_stock_price(self)

    @property
    def on_request_price(self):
        return resolve_on_request_price(self)

    @property
    def has_on_request_price(self):
        return self.on_request_price is not None

    @property
    def is_game_pack(self):
        return True

    @property
    def tracks_stock(self):
        return False


class GamePackEntry(models.Model):
    """One entry inside a game pack."""

    game_pack = models.ForeignKey(
        GamePack,
        on_delete=models.CASCADE,
        related_name='entries',
        verbose_name='Игровой пак',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='game_pack_entries',
        verbose_name='Связанный товар',
        null=True,
        blank=True,
        limit_choices_to={'is_active': True},
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    note = models.CharField('Примечание', max_length=255, blank=True)
    sort_order = models.PositiveIntegerField('Порядок', default=0)
    unresolved_title = models.CharField('Legacy title without Product match', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Позиция игрового пака'
        verbose_name_plural = 'Позиции игрового пака'
        ordering = ('sort_order', 'id')

    def __str__(self):
        title = self.product.name if self.product_id else self.unresolved_title or 'Unresolved entry'
        return f'{title} x {self.quantity}'


class GamePackServiceEntry(models.Model):
    """Included service inside a game pack."""

    game_pack = models.ForeignKey(
        GamePack,
        on_delete=models.CASCADE,
        related_name='service_entries',
        verbose_name='Игровой пак',
    )
    service = models.ForeignKey(
        'Service',
        on_delete=models.PROTECT,
        related_name='game_pack_entries',
        verbose_name='Услуга',
        null=True,
        blank=True,
        limit_choices_to={'is_active': True},
    )
    title = models.CharField('Название услуги вручную', max_length=255, blank=True)
    quantity = models.PositiveIntegerField('Количество', default=1)
    price = models.DecimalField('Цена в составе пака', max_digits=12, decimal_places=2, null=True, blank=True)
    note = models.CharField('Примечание', max_length=255, blank=True)
    sort_order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Услуга игрового пака'
        verbose_name_plural = 'Услуги игрового пака'
        ordering = ('sort_order', 'id')

    @property
    def display_title(self):
        if self.service_id:
            return self.service.name
        return self.title or 'Услуга'

    @property
    def effective_price(self):
        if self.price is not None:
            return self.price
        if self.service_id:
            return self.service.price
        return None

    def __str__(self):
        return f'{self.display_title} x {self.quantity}'


class ProductGameMetadata(models.Model):
    """B2B metadata for game products used by the VR-club constructor."""

    FORMAT_ARCADE = 'arcade'
    FORMAT_CLUB = 'club'
    FORMAT_ARENA = 'arena'
    FORMAT_MOBILE = 'mobile'
    FORMAT_CHOICES = [
        (FORMAT_ARCADE, 'Аркада / ТЦ'),
        (FORMAT_CLUB, 'VR-клуб'),
        (FORMAT_ARENA, 'Арена'),
        (FORMAT_MOBILE, 'Выездной формат'),
    ]

    product = models.OneToOneField(
        Product,
        on_delete=models.CASCADE,
        related_name='game_metadata',
        verbose_name='Игра',
        limit_choices_to={'is_active': True},
    )
    devices = models.CharField('Устройства', max_length=255, blank=True, help_text='Через запятую: Quest, Pico, PCVR')
    genres = models.CharField('Жанры', max_length=255, blank=True, help_text='Через запятую')
    min_players = models.PositiveIntegerField('Минимум игроков', default=1)
    max_players = models.PositiveIntegerField('Максимум игроков', default=1)
    age_rating = models.CharField('Возраст', max_length=40, blank=True)
    club_format = models.CharField('Формат клуба', max_length=40, choices=FORMAT_CHOICES, blank=True)
    is_pcvr = models.BooleanField('PCVR', default=False)
    is_standalone = models.BooleanField('Standalone', default=True)
    is_multiplayer = models.BooleanField('Multiplayer', default=False)
    b2b_note = models.CharField('B2B-смысл', max_length=255, blank=True)
    is_active = models.BooleanField('Показывать в конструкторе', default=True, db_index=True)
    sort_order = models.PositiveIntegerField('Порядок', default=0, db_index=True)

    class Meta:
        verbose_name = 'B2B-метаданные игры'
        verbose_name_plural = 'B2B-метаданные игр'
        ordering = ('sort_order', 'product__name')

    def __str__(self):
        return self.product.name

class GamePackItem(models.Model):
    """Текстовый состав игрового пака на карточке товара."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='game_pack_items',
        limit_choices_to={'product_kind': Product.PRODUCT_KIND_GAME_PACK},
        verbose_name='Пак игр',
    )
    title = models.CharField('Название игры', max_length=255)
    platform = models.CharField('Платформа', max_length=120, blank=True)
    note = models.CharField('Примечание', max_length=255, blank=True)
    sort_order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Игра в паке'
        verbose_name_plural = 'Игры в паке'
        ordering = ('sort_order', 'id')

    def __str__(self):
        return self.title


class City(models.Model):
    """Город с офлайн-точками выдачи."""
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('Slug', max_length=200, unique=True, blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Город'
        verbose_name_plural = 'Города'
        ordering = ('order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True)
        super().save(*args, **kwargs)


class PickupPoint(models.Model):
    """Точка выдачи в городе."""
    city = models.ForeignKey(
        City,
        on_delete=models.CASCADE,
        related_name='pickup_points',
        verbose_name='Город',
    )
    name = models.CharField('Название', max_length=255)
    address = models.TextField('Адрес', blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Точка выдачи'
        verbose_name_plural = 'Точки выдачи'
        ordering = ('order', 'name')

    def __str__(self):
        return f'{self.name} ({self.city.name})'


class ProductStock(models.Model):
    """Остаток товара в точке выдачи. variant=None — для товаров без вариантов."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name='Товар',
    )
    pickup_point = models.ForeignKey(
        PickupPoint,
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name='Точка выдачи',
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name='stocks',
        verbose_name='Вариант',
        null=True,
        blank=True,
        help_text='Пусто — остаток для товаров без вариантов',
    )
    quantity = models.PositiveIntegerField('Количество', default=0)

    class Meta:
        verbose_name = 'Остаток в точке'
        verbose_name_plural = 'Остатки в точках'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'pickup_point', 'variant'],
                name='catalog_productstock_product_pickup_variant_unique',
            ),
        ]
        ordering = ('pickup_point', 'product')

    def __str__(self):
        if self.variant:
            return f'{self.product.name} ({self.variant.name}) @ {self.pickup_point}: {self.quantity}'
        return f'{self.product.name} @ {self.pickup_point}: {self.quantity}'


class CatalogImportBatch(models.Model):
    class Status(models.TextChoices):
        REVIEW = 'review', 'На проверке'
        PARTIAL = 'partial', 'Частично применён'
        COMPLETED = 'completed', 'Завершён'
        FAILED = 'failed', 'Ошибка'

    source_filename = models.CharField('Имя исходного файла', max_length=255)
    raw_payload = models.JSONField('Исходный payload', default=dict, blank=True)
    editable_payload = models.JSONField('Редактируемый payload', default=dict, blank=True)
    summary = models.JSONField('Сводка анализа', default=dict, blank=True)
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=Status.choices,
        default=Status.REVIEW,
        db_index=True,
    )
    error_text = models.TextField('Текст ошибки', blank=True)
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Пакет импорта каталога'
        verbose_name_plural = 'Пакеты импорта каталога'
        ordering = ('-created_at',)

    def __str__(self):
        return f'Импорт каталога #{self.pk} ({self.source_filename})'


class CatalogImportConflict(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает решения'
        RESOLVED = 'resolved', 'Разрешён'
        APPLIED = 'applied', 'Применён'
        CLEARED = 'cleared', 'Устарел'

    batch = models.ForeignKey(
        CatalogImportBatch,
        on_delete=models.CASCADE,
        related_name='conflicts',
        verbose_name='Пакет импорта',
    )
    collection_name = models.CharField('Коллекция', max_length=80, db_index=True)
    source_index = models.PositiveIntegerField('Индекс в payload')
    source_id = models.CharField('Source ID', max_length=80, blank=True)
    item_label = models.CharField('Подпись элемента', max_length=255, blank=True)
    target_model = models.CharField('Модель цели', max_length=120, blank=True)
    target_pk = models.PositiveBigIntegerField('ID цели', null=True, blank=True)
    conflict_kind = models.CharField('Тип конфликта', max_length=80, db_index=True)
    source_snapshot = models.JSONField('Снимок источника', default=dict, blank=True)
    target_snapshot = models.JSONField('Снимок цели', default=dict, blank=True)
    field_conflicts = models.JSONField('Конфликтующие поля', default=dict, blank=True)
    resolutions = models.JSONField('Решения пользователя', default=dict, blank=True)
    status = models.CharField(
        'Статус',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Конфликт импорта каталога'
        verbose_name_plural = 'Конфликты импорта каталога'
        ordering = ('collection_name', 'source_index', 'id')
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'collection_name', 'source_index'],
                name='catalog_import_conflict_batch_collection_index_unique',
            ),
        ]

    def __str__(self):
        return f'{self.collection_name}[{self.source_index}] ({self.get_status_display()})'


class CartItem(models.Model):
    """Cart item persisted for an authenticated user."""

    LINE_TYPE_EQUIPMENT = 'equipment'
    LINE_TYPE_GAME = 'game'
    LINE_TYPE_SERVICE = 'service'
    LINE_TYPE_CUSTOM_GAME_PACK = 'custom_game_pack'
    LINE_TYPE_CHOICES = [
        (LINE_TYPE_EQUIPMENT, 'Оборудование'),
        (LINE_TYPE_GAME, 'Игры'),
        (LINE_TYPE_SERVICE, 'Услуга'),
        (LINE_TYPE_CUSTOM_GAME_PACK, 'Индивидуальный игровой комплект'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name='Пользователь',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='cart_items',
        verbose_name='Товар',
        null=True,
        blank=True,
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Вариант',
    )
    game_pack = models.ForeignKey(
        GamePack,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Игровой пак',
    )
    service = models.ForeignKey(
        'Service',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Услуга',
    )
    line_type = models.CharField(
        'Тип строки',
        max_length=24,
        choices=LINE_TYPE_CHOICES,
        default=LINE_TYPE_EQUIPMENT,
        db_index=True,
    )
    custom_snapshot = models.JSONField(
        'Снапшот произвольной строки',
        default=dict,
        blank=True,
        help_text='Состав индивидуального игрового комплекта или служебные данные услуги.',
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    bundle = models.ForeignKey(
        ProductBundle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Набор в корзине',
    )
    price_override = models.DecimalField(
        'Цена (override)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Используется, если в корзине была сохранена отличающаяся публичная цена.',
    )
    purchase_mode = models.CharField(
        'Режим покупки',
        max_length=20,
        choices=PURCHASE_MODE_CHOICES,
        default=PURCHASE_MODE_STOCK,
    )
    class Meta:
        verbose_name = 'Позиция корзины'
        verbose_name_plural = 'Позиции корзины'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product', 'variant', 'purchase_mode'],
                condition=models.Q(bundle__isnull=True, game_pack__isnull=True),
                name='catalog_cartitem_standalone_unique',
            ),
            models.UniqueConstraint(
                fields=['user', 'product', 'variant', 'bundle', 'purchase_mode'],
                condition=models.Q(bundle__isnull=False),
                name='catalog_cartitem_bundle_unique',
            ),
            models.UniqueConstraint(
                fields=['user', 'game_pack', 'purchase_mode'],
                condition=models.Q(game_pack__isnull=False),
                name='catalog_cartitem_game_pack_unique',
            ),
            models.UniqueConstraint(
                fields=['user', 'service'],
                condition=models.Q(service__isnull=False),
                name='catalog_cartitem_service_unique',
            ),
        ]
        ordering = ['product', 'variant', 'game_pack']
    def __str__(self):
        if self.service_id:
            return f'{self.user} ? {self.service.name} x {self.quantity}'
        if self.game_pack_id:
            return f'{self.user} ? {self.game_pack.name} x {self.quantity}'
        if self.variant:
            return f'{self.user} ? {self.product.name} ({self.variant.name}) x {self.quantity}'
        return f'{self.user} ? {self.product.name} x {self.quantity}'
class CartShare(models.Model):
    """Сохранённая ссылка на набор позиций корзины для шаринга."""
    code = models.CharField('Код', max_length=7, unique=True, db_index=True)
    items = models.JSONField('Позиции', default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_cart_shares',
        verbose_name='Создал',
    )
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    expires_at = models.DateTimeField('Действует до', db_index=True)

    class Meta:
        verbose_name = 'Шаринг корзины'
        verbose_name_plural = 'Шаринг корзины'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} ({self.created_at:%d.%m.%Y %H:%M})'


class Favorite(models.Model):
    """Избранное: пользователь + товар (уникальная пара)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='favorites',
        verbose_name='Пользователь',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='favorited_by',
        verbose_name='Товар',
    )
    created_at = models.DateTimeField('Добавлено', auto_now_add=True)

    class Meta:
        verbose_name = 'Избранное'
        verbose_name_plural = 'Избранное'
        constraints = [
            models.UniqueConstraint(fields=['user', 'product'], name='catalog_favorite_user_product_unique'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user} — {self.product.name}'


class Service(models.Model):
    """Услуга компании (страница услуг)."""

    KIND_GENERAL = 'general'
    KIND_INSTALLATION = 'installation'
    KIND_HEADSET_SETUP = 'headset_setup'
    KIND_ACCOUNTS = 'accounts'
    KIND_PCVR = 'pcvr'
    KIND_MULTIPLAYER = 'multiplayer'
    KIND_STAFF_TRAINING = 'staff_training'
    KIND_SUPPORT = 'support'
    KIND_CHOICES = [
        (KIND_GENERAL, 'Общая услуга'),
        (KIND_INSTALLATION, 'Установка'),
        (KIND_HEADSET_SETUP, 'Настройка шлемов'),
        (KIND_ACCOUNTS, 'Аккаунты'),
        (KIND_PCVR, 'PCVR'),
        (KIND_MULTIPLAYER, 'Multiplayer'),
        (KIND_STAFF_TRAINING, 'Инструкция персоналу'),
        (KIND_SUPPORT, 'Поддержка'),
    ]

    name = models.CharField('Название', max_length=200)
    short_description = models.CharField('Краткое описание', max_length=255, blank=True)
    description = models.TextField('Подробное описание', blank=True)
    icon = models.CharField(
        'Иконка (Lucide)',
        max_length=50,
        default='sparkles',
        blank=True,
        help_text='Название иконки Lucide, например: briefcase, headset, users, sparkles',
    )
    price_from = models.CharField(
        'Цена/тариф',
        max_length=80,
        blank=True,
        help_text='Например: от 15 000 ₽ или Индивидуально',
    )
    price = models.DecimalField('Цена для корзины', max_digits=12, decimal_places=2, null=True, blank=True)
    service_kind = models.CharField('Тип услуги', max_length=32, choices=KIND_CHOICES, default=KIND_GENERAL, db_index=True)
    is_vr_club_service = models.BooleanField('Услуга для VR-клубов', default=False, db_index=True)
    order = models.PositiveIntegerField('Порядок', default=0)
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлено', auto_now=True)

    class Meta:
        verbose_name = 'Услуга'
        verbose_name_plural = 'Услуги'
        ordering = ('order', 'name')

    def __str__(self):
        return self.name


class VRClubQuizRequest(models.Model):
    """Lead from the VR-club games подбор quiz."""

    name = models.CharField('Имя', max_length=150)
    phone = models.CharField('Телефон', max_length=40)
    email = models.EmailField('Email', blank=True)
    club_format = models.CharField('Формат клуба', max_length=120, blank=True)
    devices = models.CharField('Устройства', max_length=255, blank=True)
    headsets_count = models.PositiveIntegerField('Количество шлемов', null=True, blank=True)
    play_places_count = models.PositiveIntegerField('Игровых мест', null=True, blank=True)
    audience = models.CharField('Аудитория', max_length=255, blank=True)
    budget = models.CharField('Бюджет', max_length=120, blank=True)
    comment = models.TextField('Комментарий', blank=True)
    legal_accepted_at = models.DateTimeField('Согласие с юр. документами', null=True, blank=True)
    legal_docs_version = models.CharField('Версия юр. документов', max_length=32, blank=True)
    legal_acceptance_ip = models.GenericIPAddressField('IP при согласии', null=True, blank=True)
    legal_acceptance_user_agent = models.CharField('User-Agent', max_length=512, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Заявка квиза VR-клуба'
        verbose_name_plural = 'Заявки квиза VR-клуба'
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.name} — {self.created_at:%d.%m.%Y %H:%M}'


class ContactRequest(models.Model):
    """Заявка с формы обратной связи на странице контактов."""
    name = models.CharField('Имя', max_length=150)
    email = models.EmailField('Email')
    phone = models.CharField('Телефон', max_length=20, blank=True)
    message = models.TextField('Сообщение')
    legal_accepted_at = models.DateTimeField('Согласие с юр. документами', null=True, blank=True)
    legal_docs_version = models.CharField('Версия юр. документов', max_length=32, blank=True)
    legal_acceptance_ip = models.GenericIPAddressField('IP при согласии', null=True, blank=True)
    legal_acceptance_user_agent = models.CharField('User-Agent при согласии', max_length=512, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Заявка с контактов'
        verbose_name_plural = 'Заявки с контактов'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.created_at:%d.%m.%Y %H:%M}'


class CallbackRequest(models.Model):
    """Заявка на обратный звонок (страница аренды и др.)."""
    name = models.CharField('Имя', max_length=150, blank=True)
    phone = models.CharField('Телефон', max_length=20)
    source = models.CharField('Источник', max_length=50, default='arenda', blank=True)
    legal_accepted_at = models.DateTimeField('Согласие с юр. документами', null=True, blank=True)
    legal_docs_version = models.CharField('Версия юр. документов', max_length=32, blank=True)
    legal_acceptance_ip = models.GenericIPAddressField('IP при согласии', null=True, blank=True)
    legal_acceptance_user_agent = models.CharField('User-Agent при согласии', max_length=512, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Заявка на обратный звонок'
        verbose_name_plural = 'Заявки на обратный звонок'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.phone} — {self.created_at:%d.%m.%Y %H:%M}'


