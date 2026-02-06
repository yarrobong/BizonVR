from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class CatalogSection(models.Model):
    """Раздел каталога в меню: Решения для VR бизнеса, VR-аттракционы и т.д."""
    name = models.CharField('Название', max_length=200)
    slug = models.SlugField('Slug', max_length=200, unique=True, blank=True)
    order = models.PositiveIntegerField('Порядок', default=0)

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
    created_at = models.DateTimeField('Создан', auto_now_add=True)
    updated_at = models.DateTimeField('Обновлён', auto_now=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ('-created_at',)

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


class ProductVariant(models.Model):
    """Вариант товара: цвет, размер, модель и т.п. Своё фото и цена (опционально)."""
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='variants',
        verbose_name='Товар',
    )
    name = models.CharField('Название', max_length=100)
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
    order = models.PositiveIntegerField('Порядок', default=0)

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
    """Набор товаров. Состав и цены задаются вручную через ProductBundleItem."""
    name = models.CharField(
        'Название набора',
        max_length=200,
        blank=True,
        help_text='Для отображения в админке и на странице товара',
    )

    class Meta:
        verbose_name = 'Набор товаров'
        verbose_name_plural = 'Наборы товаров'

    def __str__(self):
        if self.name:
            return self.name
        items = self.items.select_related('product').all()[:3]
        names = [f'{i.product.name} ({i.price} ₽)' for i in items]
        return ' + '.join(names) if names else f'Набор #{self.pk}'

    @property
    def total_price(self):
        """Сумма цен всех позиций набора (price × quantity по каждой позиции)."""
        total = sum(float(i.price) * i.quantity for i in self.items.all())
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
        help_text='Цена за единицу при покупке в составе набора',
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

    def __str__(self):
        return f'{self.product.name} × {self.quantity} — {self.price} ₽'


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


class ContactRequest(models.Model):
    """Заявка с формы обратной связи на странице контактов."""
    name = models.CharField('Имя', max_length=150)
    email = models.EmailField('Email')
    phone = models.CharField('Телефон', max_length=20, blank=True)
    message = models.TextField('Сообщение')
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        verbose_name = 'Заявка с контактов'
        verbose_name_plural = 'Заявки с контактов'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} — {self.created_at:%d.%m.%Y %H:%M}'
