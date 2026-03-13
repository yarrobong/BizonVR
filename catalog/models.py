from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from config.formatting import format_currency_amount


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
    price = models.DecimalField('Цена', max_digits=12, decimal_places=2)
    image = models.ImageField('Изображение', upload_to='products/', blank=True, null=True)
    is_active = models.BooleanField('Активен', default=True)
    allow_order_on_request = models.BooleanField(
        'Доступен под заказ',
        default=True,
        help_text='Если товара нет в наличии, покупатель может оформить заказ под заказ',
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
    shipping_weight_kg = models.DecimalField(
        'Вес отправки, кг',
        max_digits=7,
        decimal_places=3,
        default=Decimal('0.500'),
        help_text='Используется для расчёта доставки CDEK на один товар.',
    )
    shipping_length_cm = models.PositiveIntegerField(
        'Длина упаковки, см',
        default=25,
        help_text='Используется для расчёта доставки CDEK на один товар.',
    )
    shipping_width_cm = models.PositiveIntegerField(
        'Ширина упаковки, см',
        default=20,
        help_text='Используется для расчёта доставки CDEK на один товар.',
    )
    shipping_height_cm = models.PositiveIntegerField(
        'Высота упаковки, см',
        default=15,
        help_text='Используется для расчёта доставки CDEK на один товар.',
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
    def shipping_volume_cm3(self):
        return self.shipping_length_cm * self.shipping_width_cm * self.shipping_height_cm


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
        'Цена (переопределение)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Пусто — использовать цену товара',
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
        total = sum(float(i.product.price) * i.quantity for i in self.items.all())
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
            self.price = (Decimal(str(self.product.price)) * Decimal('0.95')).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)

    @property
    def effective_price(self):
        """Цена за единицу в комплекте (автоматически −5% от цены товара)."""
        if self.product_id:
            return (Decimal(str(self.product.price)) * Decimal('0.95')).quantize(Decimal('0.01'))
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
        'Цена (в комплекте со скидкой)',
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Если задана — в корзине используется эта цена вместо цены товара',
    )

    class Meta:
        verbose_name = 'Позиция корзины'
        verbose_name_plural = 'Позиции корзины'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product', 'variant'],
                condition=models.Q(bundle__isnull=True),
                name='catalog_cartitem_standalone_unique',
            ),
            models.UniqueConstraint(
                fields=['user', 'product', 'variant', 'bundle'],
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


class CompareItem(models.Model):
    """Товар пользователя в списке сравнения."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='compare_items',
        verbose_name='Пользователь',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='compared_by',
        verbose_name='Товар',
    )
    created_at = models.DateTimeField('Добавлено', auto_now_add=True)

    class Meta:
        verbose_name = 'Сравнение'
        verbose_name_plural = 'Сравнение'
        constraints = [
            models.UniqueConstraint(fields=['user', 'product'], name='catalog_compareitem_user_product_unique'),
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
