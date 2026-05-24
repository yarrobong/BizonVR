from datetime import timedelta

from django.contrib.admin import AdminSite
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone


# Логические группы для главной страницы админ-панели.
# Ключ — название группы, значение — список model object_name в нужном порядке.
ADMIN_GROUPS = [
    (
        "Продажи",
        [
            "Order",
            "OrderItem",
            "PromoCode",
            "PurchaseRequest",
            "Payment",
            "OrderNotificationLog",
            "CartItem",
            "Favorite",
        ],
    ),
    (
        "Каталог",
        [
            "Product",
            "ProductVariant",
            "ProductBundle",
            "GamePack",
            "GamePackEntry",
            "GamePackServiceEntry",
            "ProductGameMetadata",
            "ProductContentBlock",
            "DescriptionBlockType",
            "DescriptionTemplate",
            "ProductDescription",
            "CatalogSection",
            "Category",
            "ProductTag",
            "Service",
        ],
    ),
    (
        "Склад",
        [
            "City",
            "PickupPoint",
            "ProductStock",
            "Warehouse",
            "InventoryBalance",
            "InventoryMovement",
            "InventoryLot",
            "SaleLineAllocation",
            "Purchase",
            "Cargo",
            "TransportLeg",
            "Expense",
        ],
    ),
    (
        "CRM",
        [
            "ContactRequest",
            "CallbackRequest",
            "VRClubQuizRequest",
            "ManagerClient",
            "ManagerDeal",
            "DealActivity",
            "DealSavedView",
            "TradeInItem",
            "Reservation",
        ],
    ),
    (
        "Документы",
        [
            "ContractDocument",
            "ContractTemplate",
            "ContractCompanyProfile",
            "FinanceDeal",
            "FinanceDealLine",
            "FinanceDealShare",
            "FinanceDealAdjustment",
            "FinancePayout",
            "FinanceDealType",
            "FinanceDistributionScheme",
            "FinanceDistributionRule",
            "FinanceExpenseCategory",
            "FinanceExpense",
        ],
    ),
    (
        "Настройки",
        [
            "CharacteristicDefinition",
            "CharacteristicSourceAlias",
            "CharacteristicValueAlias",
            "FilterConfig",
            "User",
            "Profile",
            "Group",
            "PhoneVerificationCode",
            "EmailVerificationCode",
        ],
    ),
]


class GroupedAdminSite(AdminSite):
    """AdminSite с группировкой моделей по логическим разделам."""

    index_template = "admin/index.html"

    def get_urls(self):
        from warehouse_ui import views as warehouse_views

        custom_urls = [
            path('warehouse/', self.admin_view(warehouse_views.warehouse_index_view), name='warehouse_ui_index'),
            path('warehouse/matrix/', self.admin_view(warehouse_views.warehouse_matrix_view), name='warehouse_ui_matrix'),
            path('warehouse/items/<str:sku_key>/drawer/', self.admin_view(warehouse_views.warehouse_drawer_view), name='warehouse_ui_drawer'),
            path('warehouse/items/<str:sku_key>/history/', self.admin_view(warehouse_views.warehouse_history_view), name='warehouse_ui_history'),
            path('warehouse/actions/receipt/', self.admin_view(warehouse_views.warehouse_receipt_action_view), name='warehouse_ui_receipt_action'),
            path('warehouse/actions/adjustment/', self.admin_view(warehouse_views.warehouse_adjustment_action_view), name='warehouse_ui_adjustment_action'),
            path('warehouse/actions/transfer/', self.admin_view(warehouse_views.warehouse_transfer_action_view), name='warehouse_ui_transfer_action'),
        ]
        return custom_urls + super().get_urls()

    def get_app_list(self, request, app_label=None):
        original = super().get_app_list(request, app_label)

        # Если запрошен конкретный app — возвращаем без изменений
        # (используется на страницах списка/формы конкретного приложения)
        if app_label is not None:
            return original

        # Собираем все модели в один словарь: object_name → model_dict
        all_models: dict[str, dict] = {}
        for app in original:
            for model in app["models"]:
                all_models[model["object_name"]] = model

        grouped = []
        assigned_names: set[str] = set()

        for group_name, model_names in ADMIN_GROUPS:
            models_in_group = []
            for name in model_names:
                if name in all_models:
                    models_in_group.append(all_models[name])
                    assigned_names.add(name)

            if models_in_group:
                grouped.append(
                    {
                        "name": group_name,
                        "app_label": group_name.lower().replace(" ", "_"),
                        "app_url": "",
                        "has_module_perms": True,
                        "models": models_in_group,
                    }
                )

        # Модели, не попавшие ни в одну группу — добавляем в конец
        leftover = [m for name, m in all_models.items() if name not in assigned_names]
        if leftover:
            grouped.append(
                {
                    "name": "Прочее",
                    "app_label": "other",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": leftover,
                }
            )

        return grouped

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(self._build_dashboard_context(request))
        return super().index(request, extra_context=extra_context)

    def _admin_changelist_url(self, model):
        try:
            return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        except NoReverseMatch:
            return ""

    def _admin_change_url(self, obj):
        try:
            return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
        except NoReverseMatch:
            return ""

    def _can_access_model(self, request, model):
        opts = model._meta
        return any(
            request.user.has_perm(f"{opts.app_label}.{action}_{opts.model_name}")
            for action in ("view", "change", "add", "delete")
        )

    def _build_dashboard_context(self, request):
        from catalog.models import CallbackRequest, ContactRequest, Product, ProductStock, VRClubQuizRequest
        from orders.models import Order

        since = timezone.now() - timedelta(days=1)
        low_stock_threshold = 2
        can_view_contact_requests = self._can_access_model(request, ContactRequest)
        can_view_callback_requests = self._can_access_model(request, CallbackRequest)
        can_view_vr_club_requests = self._can_access_model(request, VRClubQuizRequest)
        can_view_leads = any((can_view_contact_requests, can_view_callback_requests, can_view_vr_club_requests))
        can_view_orders = self._can_access_model(request, Order)
        can_view_products = self._can_access_model(request, Product)
        can_view_stocks = self._can_access_model(request, ProductStock)

        lead_count_24h = 0
        if can_view_contact_requests:
            lead_count_24h += ContactRequest.objects.filter(created_at__gte=since).count()
        if can_view_callback_requests:
            lead_count_24h += CallbackRequest.objects.filter(created_at__gte=since).count()
        if can_view_vr_club_requests:
            lead_count_24h += VRClubQuizRequest.objects.filter(created_at__gte=since).count()
        if not can_view_leads:
            lead_count_24h = None
        new_orders_count = Order.objects.filter(status=Order.STATUS_NEW).count() if can_view_orders else None

        base_product_issue_qs = (
            Product.objects.filter(is_active=True)
            .annotate(
                extra_image_count=Count("images", distinct=True),
                variant_image_count=Count("variants", filter=Q(variants__image__isnull=False), distinct=True),
            )
            .select_related("category")
            .order_by("-updated_at")
        )
        products_without_images = list(
            base_product_issue_qs.filter(
                image__isnull=True,
                extra_image_count=0,
                variant_image_count=0,
            )[:4]
        ) if can_view_products else []
        products_without_prices = list(
            base_product_issue_qs.filter(
                price__isnull=True,
                price_on_request__isnull=True,
            )[:4]
        ) if can_view_products else []
        product_issue_count = (
            base_product_issue_qs.filter(
                Q(
                    image__isnull=True,
                    extra_image_count=0,
                    variant_image_count=0,
                )
                | Q(price__isnull=True, price_on_request__isnull=True)
            )
            .values("pk")
            .distinct()
            .count()
        ) if can_view_products else None

        stock_problem_qs = (
            Product.objects.filter(is_active=True, product_kind=Product.PRODUCT_KIND_PHYSICAL)
            .exclude(game_metadata__is_active=True)
            .annotate(stock_total=Coalesce(Sum("stocks__quantity"), Value(0)))
            .select_related("category")
            .order_by("stock_total", "-updated_at")
        )
        out_of_stock_products = list(stock_problem_qs.filter(stock_total__lte=0)[:4]) if can_view_products else []
        low_stock_products = list(
            stock_problem_qs.filter(stock_total__gt=0, stock_total__lte=low_stock_threshold)[:4]
        ) if can_view_products else []
        stock_issue_count = stock_problem_qs.filter(stock_total__lte=low_stock_threshold).count() if can_view_stocks else None

        lead_items = []
        if can_view_leads:
            lead_sources = []
            if can_view_contact_requests:
                lead_sources.append(("contact", "Контакты", ContactRequest.objects.order_by("-created_at")[:4]))
            if can_view_callback_requests:
                lead_sources.append(("callback", "Обратный звонок", CallbackRequest.objects.order_by("-created_at")[:4]))
            if can_view_vr_club_requests:
                lead_sources.append(("vr_club", "VR-клуб", VRClubQuizRequest.objects.order_by("-created_at")[:4]))
            for lead_type, label, queryset in lead_sources:
                for item in queryset:
                    lead_items.append(
                        {
                            "kind": lead_type,
                            "label": label,
                            "title": getattr(item, "name", "") or getattr(item, "phone", "Без имени"),
                            "meta": getattr(item, "phone", "") or getattr(item, "email", ""),
                            "created_at": item.created_at,
                            "url": self._admin_change_url(item),
                        }
                    )
            lead_items.sort(key=lambda item: item["created_at"], reverse=True)

        order_items = [
            {
                "title": f"Заказ #{order.pk}",
                "meta": " / ".join(
                    part for part in [order.first_name or order.phone or order.email, order.get_payment_status_display()] if part
                ),
                "status": order.get_status_display(),
                "created_at": order.created_at,
                "url": self._admin_change_url(order),
            }
            for order in Order.objects.filter(status=Order.STATUS_NEW).order_by("-created_at")[:6]
        ] if can_view_orders else []

        product_issue_items = []
        for product in products_without_images:
            product_issue_items.append(
                {
                    "title": product.name,
                    "issue": "Нет изображения",
                    "meta": getattr(product.category, "name", ""),
                    "url": self._admin_change_url(product),
                }
            )
        for product in products_without_prices:
            product_issue_items.append(
                {
                    "title": product.name,
                    "issue": "Нет цены и цены под заказ",
                    "meta": getattr(product.category, "name", ""),
                    "url": self._admin_change_url(product),
                }
            )

        seen_product_ids = set()
        unique_product_issue_items = []
        for item in product_issue_items:
            product_id = item["url"]
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)
            unique_product_issue_items.append(item)

        stock_issue_items = []
        for product in out_of_stock_products:
            stock_issue_items.append(
                {
                    "title": product.name,
                    "issue": "Нет остатка",
                    "meta": getattr(product.category, "name", ""),
                    "stock_total": product.stock_total,
                    "url": self._admin_change_url(product),
                }
            )
        for product in low_stock_products:
            stock_issue_items.append(
                {
                    "title": product.name,
                    "issue": "Мало остатка",
                    "meta": getattr(product.category, "name", ""),
                    "stock_total": product.stock_total,
                    "url": self._admin_change_url(product),
                }
            )

        seen_stock_urls = set()
        unique_stock_issue_items = []
        for item in stock_issue_items:
            if item["url"] in seen_stock_urls:
                continue
            seen_stock_urls.add(item["url"])
            unique_stock_issue_items.append(item)

        summary = []
        if can_view_leads:
            summary.append(
                {
                    "label": "Новые заявки за 24 часа",
                    "value": lead_count_24h,
                    "url": self._admin_changelist_url(ContactRequest),
                }
            )
        if can_view_orders:
            summary.append(
                {
                    "label": "Заказы ждут обработки",
                    "value": new_orders_count,
                    "url": self._admin_changelist_url(Order),
                }
            )
        if can_view_products:
            summary.append(
                {
                    "label": "Проблемы в товарах",
                    "value": product_issue_count,
                    "url": self._admin_changelist_url(Product),
                }
            )
        if can_view_stocks:
            summary.append(
                {
                    "label": "Проблемы с остатками",
                    "value": stock_issue_count,
                    "url": self._admin_changelist_url(ProductStock),
                }
            )
        if request.user.is_staff:
            summary.append(
                {
                    "label": "Склад v1",
                    "value": "Открыть",
                    "url": reverse('admin:warehouse_ui_index'),
                }
            )

        queues = []
        if can_view_leads:
            queues.append(
                {
                    "title": "Новые заявки",
                    "empty": "Новых заявок пока нет.",
                    "items": lead_items[:6],
                }
            )
        if can_view_orders:
            queues.append(
                {
                    "title": "Новые заказы",
                    "empty": "Новых заказов без обработки нет.",
                    "items": order_items,
                }
            )
        if can_view_products:
            queues.append(
                {
                    "title": "Проблемы товаров",
                    "empty": "Критичных проблем в карточках товаров не найдено.",
                    "items": unique_product_issue_items[:6],
                }
            )
        if can_view_products and can_view_stocks:
            queues.append(
                {
                    "title": "Проблемы остатков",
                    "empty": "Критичных проблем с остатками не найдено.",
                    "items": unique_stock_issue_items[:6],
                }
            )

        return {"task_dashboard": {"summary": summary, "queues": queues}}
