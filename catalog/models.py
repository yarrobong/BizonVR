import html
import re
from decimal import Decimal
from urllib.parse import urlparse

import requests

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from config.formatting import format_currency_amount
from .pricing import (
    PURCHASE_MODE_CHOICES,
    PURCHASE_MODE_STOCK,
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
    price = models.DecimalField('Цена из наличия', max_digits=12, decimal_places=2, null=True, blank=True)
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

    class Meta:
        verbose_name = 'Набор товаров'
        verbose_name_plural = 'Наборы товаров'

    def __str__(self):
        return self.name or f'Набор #{self.pk}'

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

    @property
    def total_price(self):
        """Сумма цен всех позиций набора (со скидкой −5%)."""
        total = sum(float(i.effective_price) * i.quantity for i in self.items.all())
        return total

    @property
    def total_price_without_discount(self):
        """Сумма по полным ценам товаров (без скидки)."""
        total = sum(float(resolve_in_stock_price(i.product) or 0) * i.quantity for i in self.items.all())
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
        help_text='Рассчитывается автоматически: −5% от цены товара при покупке полного набора',
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
                self.price = (Decimal(str(base_price)) * Decimal('0.95')).quantize(Decimal('0.01'))
            else:
                self.price = None
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        """Цена за единицу в комплекте (автоматически −5% от цены товара)."""
        if self.product_id:
            base_price = resolve_in_stock_price(self.product)
            if base_price is not None:
                return (Decimal(str(base_price)) * Decimal('0.95')).quantize(Decimal('0.01'))
        return Decimal('0')

    def __str__(self):
        return f'{self.product.name} × {self.quantity} — {format_currency_amount(self.effective_price)}'


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


class CartItem(models.Model):
    """Позиция корзины: привязка к пользователю для сохранения между сессиями."""
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
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Вариант',
    )
    quantity = models.PositiveIntegerField('Количество', default=1)
    bundle = models.ForeignKey(
        ProductBundle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cart_items',
        verbose_name='Входит в комплект',
    )
    price_override = models.DecimalField(
        'Цена (override)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Если задана — в корзине используется эта цена вместо текущей цены товара.',
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
                condition=models.Q(bundle__isnull=True),
                name='catalog_cartitem_standalone_unique',
            ),
            models.UniqueConstraint(
                fields=['user', 'product', 'variant', 'bundle', 'purchase_mode'],
                condition=models.Q(bundle__isnull=False),
                name='catalog_cartitem_bundle_unique',
            ),
        ]
        ordering = ['product', 'variant']

    def __str__(self):
        if self.variant:
            return f'{self.user} — {self.product.name} ({self.variant.name}) x {self.quantity}'
        return f'{self.user} — {self.product.name} x {self.quantity}'


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
