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
    """Остаток товара в точке выдачи."""
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
    quantity = models.PositiveIntegerField('Количество', default=0)

    class Meta:
        verbose_name = 'Остаток в точке'
        verbose_name_plural = 'Остатки в точках'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'pickup_point'],
                name='catalog_productstock_product_pickup_unique',
            ),
        ]
        ordering = ('pickup_point', 'product')

    def __str__(self):
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
