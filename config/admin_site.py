from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.admin import AdminSite
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone


ADMIN_SECTIONS = [
    {
        "name": "Продажи",
        "anchor": "sales",
        "description": "Заказы, оплаты, промокоды и заявки на покупку.",
        "models": [
            "Order",
            "OrderItem",
            "PromoCode",
            "PurchaseRequest",
            "Payment",
            "OrderNotificationLog",
            "CartItem",
            "Favorite",
        ],
    },
    {
        "name": "Каталог",
        "anchor": "catalog",
        "description": "Товары, игровые паки, подборки и структура каталога.",
        "models": [
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
    },
    {
        "name": "Склад",
        "anchor": "warehouse",
        "description": "Остатки, склады, закупки и движения товаров.",
        "models": [
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
    },
    {
        "name": "CRM",
        "anchor": "crm",
        "description": "Клиенты, сделки, обращения и бронь.",
        "models": [
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
    },
    {
        "name": "Документы",
        "anchor": "documents",
        "description": "Договоры, шаблоны и профили компаний.",
        "models": [
            "ContractDocument",
            "ContractTemplate",
            "ContractCompanyProfile",
        ],
    },
    {
        "name": "Финансы",
        "anchor": "finance",
        "description": "Финансовые сделки, выплаты и расходы.",
        "models": [
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
    },
    {
        "name": "Настройки",
        "anchor": "settings",
        "description": "Характеристики, фильтры, пользователи, права и системные справочники.",
        "models": [
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
    },
]

TECHNICAL_HOME_MODELS = {
    "OrderItem",
    "CartItem",
    "Favorite",
    "OrderNotificationLog",
    "GamePackEntry",
    "GamePackServiceEntry",
    "ProductContentBlock",
    "ProductDescription",
    "DescriptionBlockType",
    "CharacteristicSourceAlias",
    "CharacteristicValueAlias",
    "DealActivity",
    "DealSavedView",
    "SaleLineAllocation",
    "FinanceDealLine",
    "FinanceDealShare",
    "FinanceDealAdjustment",
}

SEARCH_LIMIT_PER_MODEL = 5
FOCUS_LIMIT = 24
LOW_STOCK_THRESHOLD = 2


class GroupedAdminSite(AdminSite):
    """AdminSite с задачной главной страницей вместо плоского списка моделей."""

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
            path('warehouse/actions/reserve/', self.admin_view(warehouse_views.warehouse_reserve_action_view), name='warehouse_ui_reserve_action'),
            path('warehouse/actions/expense/', self.admin_view(warehouse_views.warehouse_expense_action_view), name='warehouse_ui_expense_action'),
            path('warehouse/actions/writeoff/', self.admin_view(warehouse_views.warehouse_writeoff_action_view), name='warehouse_ui_writeoff_action'),
            path('warehouse/export/', self.admin_view(warehouse_views.warehouse_export_view), name='warehouse_ui_export'),
            path('warehouse/print/', self.admin_view(warehouse_views.warehouse_print_view), name='warehouse_ui_print'),
        ]
        return custom_urls + super().get_urls()

    def get_app_list(self, request, app_label=None):
        original = super().get_app_list(request, app_label)
        if app_label is not None:
            return original

        all_models: dict[str, dict] = {}
        for app in original:
            for model in app["models"]:
                all_models[model["object_name"]] = model

        grouped = []
        assigned_names: set[str] = set()

        for section in ADMIN_SECTIONS:
            models_in_group = []
            for model_name in section["models"]:
                if model_name in all_models:
                    models_in_group.append(all_models[model_name])
                    assigned_names.add(model_name)

            if models_in_group:
                grouped.append(
                    {
                        "name": section["name"],
                        "app_label": section["anchor"],
                        "app_url": "",
                        "has_module_perms": True,
                        "models": models_in_group,
                    }
                )

        leftovers = [model for name, model in all_models.items() if name not in assigned_names]
        if leftovers:
            grouped.append(
                {
                    "name": "Прочее",
                    "app_label": "other",
                    "app_url": "",
                    "has_module_perms": True,
                    "models": leftovers,
                }
            )

        return grouped

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        app_list = self.get_app_list(request)
        extra_context.update(self._build_home_context(request, app_list))
        extra_context["is_nav_sidebar_enabled"] = False
        return super().index(request, extra_context=extra_context)

    def _admin_changelist_url(self, model):
        try:
            return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        except NoReverseMatch:
            return ""

    def _admin_add_url(self, model):
        try:
            return reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_add")
        except NoReverseMatch:
            return ""

    def _admin_change_url(self, obj):
        try:
            return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])
        except NoReverseMatch:
            return ""

    def _index_url(self, **params):
        base_url = reverse("admin:index")
        filtered = {key: value for key, value in params.items() if value not in (None, "")}
        if not filtered:
            return base_url
        return f"{base_url}?{urlencode(filtered)}"

    def _purchase_request_meta(self, purchase_request):
        parts = []
        if purchase_request.telegram:
            parts.append(purchase_request.telegram)

        items = purchase_request.items if isinstance(purchase_request.items, list) else []
        item_names = []
        for item in items[:2]:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            quantity = item.get("quantity")
            if not name:
                continue
            if quantity:
                item_names.append(f"{name} x{quantity}")
            else:
                item_names.append(name)
        if len(items) > 2:
            item_names.append(f"+{len(items) - 2} поз.")
        if item_names:
            parts.append(", ".join(item_names))

        return " / ".join(parts)

    def _can_access_model(self, request, model):
        opts = model._meta
        return any(
            request.user.has_perm(f"{opts.app_label}.{action}_{opts.model_name}")
            for action in ("view", "change", "add", "delete")
        )

    def _can_add_model(self, request, model):
        opts = model._meta
        return request.user.has_perm(f"{opts.app_label}.add_{opts.model_name}")

    def _section_by_name(self):
        return {section["name"]: section for section in ADMIN_SECTIONS}

    def _section_name_by_model(self):
        mapping = {}
        for section in ADMIN_SECTIONS:
            for model_name in section["models"]:
                mapping[model_name] = section["name"]
        return mapping

    def _build_home_context(self, request, app_list):
        dashboard = self._build_dashboard_context(request)
        home_sections = self._build_home_sections(app_list)
        search = self._build_search_context(request)

        navigation = [
            {"label": "Главная", "anchor": "overview"},
            *[
                {
                    "label": section["name"],
                    "anchor": section["anchor"],
                }
                for section in home_sections["sections"]
            ],
        ]
        if home_sections["service_sections"]:
            navigation.append({"label": "Служебное", "anchor": "service"})

        return {
            "admin_home": {
                "navigation": navigation,
                "sections": home_sections["sections"],
                "service_sections": home_sections["service_sections"],
                "search": search,
                **dashboard,
            }
        }

    def _build_home_sections(self, app_list):
        section_meta = self._section_by_name()
        main_sections = []
        service_sections = []

        for app in app_list:
            section = section_meta.get(app["name"])
            if section is None:
                service_sections.append(
                    {
                        "name": app["name"],
                        "anchor": "service",
                        "models": app["models"],
                    }
                )
                continue

            visible_models = []
            hidden_models = []
            for model in app["models"]:
                if model["object_name"] in TECHNICAL_HOME_MODELS:
                    hidden_models.append(model)
                else:
                    visible_models.append(model)

            if visible_models:
                main_sections.append(
                    {
                        "name": app["name"],
                        "anchor": section["anchor"],
                        "description": section["description"],
                        "models": visible_models,
                    }
                )
            if hidden_models:
                service_sections.append(
                    {
                        "name": app["name"],
                        "anchor": "service",
                        "models": hidden_models,
                    }
                )

        return {"sections": main_sections, "service_sections": service_sections}

    def _build_search_context(self, request):
        query = (request.GET.get("q") or "").strip()
        if not query:
            return {"query": "", "results": [], "total": 0}

        section_by_model = self._section_name_by_model()
        grouped_results = []
        total = 0

        for model, model_admin in self._registry.items():
            if not self._can_access_model(request, model):
                continue
            if not getattr(model_admin, "search_fields", None):
                continue

            queryset = model_admin.get_queryset(request)
            queryset, may_have_duplicates = model_admin.get_search_results(request, queryset, query)
            if may_have_duplicates:
                queryset = queryset.distinct()
            objects = list(queryset[:SEARCH_LIMIT_PER_MODEL])
            if not objects:
                continue

            items = []
            for obj in objects:
                items.append(
                    {
                        "title": str(obj),
                        "meta": model._meta.verbose_name,
                        "url": self._admin_change_url(obj),
                    }
                )

            grouped_results.append(
                {
                    "section": section_by_model.get(model.__name__, "Служебное"),
                    "model_name": model._meta.verbose_name_plural,
                    "model_url": self._admin_changelist_url(model),
                    "items": items,
                }
            )
            total += len(items)

        grouped_results.sort(key=lambda item: (item["section"], item["model_name"]))
        return {"query": query, "results": grouped_results, "total": total}

    def _build_dashboard_context(self, request):
        from catalog.models import CallbackRequest, ContactRequest, Product, ProductStock, VRClubQuizRequest
        from manager_portal.models import ContractDocument, ManagerClient
        from orders.models import Order, PurchaseRequest

        since = timezone.now() - timedelta(days=1)

        can_view_contact_requests = self._can_access_model(request, ContactRequest)
        can_view_callback_requests = self._can_access_model(request, CallbackRequest)
        can_view_vr_club_requests = self._can_access_model(request, VRClubQuizRequest)
        can_view_leads = any((can_view_contact_requests, can_view_callback_requests, can_view_vr_club_requests))
        can_view_orders = self._can_access_model(request, Order)
        can_view_purchase_requests = self._can_access_model(request, PurchaseRequest)
        can_view_products = self._can_access_model(request, Product)
        can_view_stocks = self._can_access_model(request, ProductStock)

        lead_count_24h = 0
        lead_items = []
        if can_view_contact_requests:
            recent_contact_qs = ContactRequest.objects.filter(created_at__gte=since).order_by("-created_at")
            lead_count_24h += recent_contact_qs.count()
            lead_items.extend(
                {
                    "title": item.name or item.email,
                    "meta": " / ".join(part for part in [item.phone, item.email] if part),
                    "created_at": item.created_at,
                    "label": "Контакты",
                    "url": self._admin_change_url(item),
                }
                for item in recent_contact_qs[:6]
            )
        if can_view_callback_requests:
            recent_callback_qs = CallbackRequest.objects.filter(created_at__gte=since).order_by("-created_at")
            lead_count_24h += recent_callback_qs.count()
            lead_items.extend(
                {
                    "title": item.name or item.phone,
                    "meta": item.phone,
                    "created_at": item.created_at,
                    "label": "Обратный звонок",
                    "url": self._admin_change_url(item),
                }
                for item in recent_callback_qs[:6]
            )
        if can_view_vr_club_requests:
            recent_vr_club_qs = VRClubQuizRequest.objects.filter(created_at__gte=since).order_by("-created_at")
            lead_count_24h += recent_vr_club_qs.count()
            lead_items.extend(
                {
                    "title": item.name or item.phone,
                    "meta": " / ".join(part for part in [item.phone, item.devices] if part),
                    "created_at": item.created_at,
                    "label": "VR-клуб",
                    "url": self._admin_change_url(item),
                }
                for item in recent_vr_club_qs[:6]
            )
        if not can_view_leads:
            lead_count_24h = None
        lead_items.sort(key=lambda item: item["created_at"], reverse=True)

        new_orders_qs = Order.objects.filter(status=Order.STATUS_NEW).order_by("-created_at") if can_view_orders else Order.objects.none()
        new_orders_count = new_orders_qs.count() if can_view_orders else None
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
            for order in new_orders_qs[:6]
        ]

        purchase_request_qs = (
            PurchaseRequest.objects.filter(status=PurchaseRequest.STATUS_NEW).order_by("-created_at")
            if can_view_purchase_requests
            else PurchaseRequest.objects.none()
        )
        purchase_request_count = purchase_request_qs.count() if can_view_purchase_requests else None
        purchase_request_items = [
            {
                "title": item.phone or f"Заявка #{item.pk}",
                "meta": self._purchase_request_meta(item),
                "status": item.get_status_display(),
                "created_at": item.created_at,
                "url": self._admin_change_url(item),
            }
            for item in purchase_request_qs[:6]
        ]

        base_product_issue_qs = (
            Product.objects.filter(is_active=True)
            .annotate(
                extra_image_count=Count("images", distinct=True),
                variant_image_count=Count("variants", filter=Q(variants__image__isnull=False), distinct=True),
            )
            .select_related("category")
            .order_by("-updated_at")
        )
        products_without_images = (
            list(
                base_product_issue_qs.filter(
                    image__isnull=True,
                    extra_image_count=0,
                    variant_image_count=0,
                )[:FOCUS_LIMIT]
            )
            if can_view_products
            else []
        )
        products_without_prices = (
            list(
                base_product_issue_qs.filter(
                    price__isnull=True,
                    price_on_request__isnull=True,
                )[:FOCUS_LIMIT]
            )
            if can_view_products
            else []
        )
        product_issue_count = (
            base_product_issue_qs.filter(
                Q(image__isnull=True, extra_image_count=0, variant_image_count=0)
                | Q(price__isnull=True, price_on_request__isnull=True)
            )
            .values("pk")
            .distinct()
            .count()
            if can_view_products
            else None
        )

        product_issue_preview = []
        for product in products_without_images[:4]:
            product_issue_preview.append(
                {
                    "title": product.name,
                    "issue": "Нет изображения",
                    "meta": getattr(product.category, "name", ""),
                    "url": self._admin_change_url(product),
                }
            )
        for product in products_without_prices[:4]:
            product_issue_preview.append(
                {
                    "title": product.name,
                    "issue": "Нет цены",
                    "meta": getattr(product.category, "name", ""),
                    "url": self._admin_change_url(product),
                }
            )

        seen_issue_urls = set()
        unique_product_issue_preview = []
        for item in product_issue_preview:
            if item["url"] in seen_issue_urls:
                continue
            seen_issue_urls.add(item["url"])
            unique_product_issue_preview.append(item)

        stock_problem_qs = (
            Product.objects.filter(is_active=True, product_kind=Product.PRODUCT_KIND_PHYSICAL)
            .exclude(game_metadata__is_active=True)
            .annotate(stock_total=Coalesce(Sum("stocks__quantity"), Value(0)))
            .select_related("category")
            .order_by("stock_total", "-updated_at")
        )
        out_of_stock_products = list(stock_problem_qs.filter(stock_total__lte=0)[:FOCUS_LIMIT]) if can_view_products else []
        low_stock_products = (
            list(stock_problem_qs.filter(stock_total__gt=0, stock_total__lte=LOW_STOCK_THRESHOLD)[:FOCUS_LIMIT])
            if can_view_products
            else []
        )
        stock_issue_count = (
            stock_problem_qs.filter(stock_total__lte=LOW_STOCK_THRESHOLD).count()
            if can_view_stocks
            else None
        )

        stock_issue_preview = []
        for product in out_of_stock_products[:4]:
            stock_issue_preview.append(
                {
                    "title": product.name,
                    "issue": "Нет остатка",
                    "meta": getattr(product.category, "name", ""),
                    "stock_total": product.stock_total,
                    "url": self._admin_change_url(product),
                }
            )
        for product in low_stock_products[:4]:
            stock_issue_preview.append(
                {
                    "title": product.name,
                    "issue": "Мало остатка",
                    "meta": getattr(product.category, "name", ""),
                    "stock_total": product.stock_total,
                    "url": self._admin_change_url(product),
                }
            )

        seen_stock_urls = set()
        unique_stock_issue_preview = []
        for item in stock_issue_preview:
            if item["url"] in seen_stock_urls:
                continue
            seen_stock_urls.add(item["url"])
            unique_stock_issue_preview.append(item)

        focus_panels = {}
        if can_view_leads:
            focus_panels["leads_recent"] = {
                "title": "Новые заявки за 24 часа",
                "description": "Контакты, обратные звонки и VR-клубы за последние сутки.",
                "items": lead_items[:FOCUS_LIMIT],
            }
        if can_view_orders:
            focus_panels["orders_new"] = {
                "title": "Новые заказы",
                "description": "Заказы со статусом «Новый», которые менеджеру нужно взять в работу.",
                "items": [
                    {
                        **item,
                        "badge": item.get("status"),
                    }
                    for item in order_items[:FOCUS_LIMIT]
                ],
            }
        if can_view_purchase_requests:
            focus_panels["purchase_requests_new"] = {
                "title": "Новые заявки на покупку",
                "description": "Заявки со статусом «Новая», ожидающие первого контакта.",
                "items": [
                    {
                        **item,
                        "badge": item.get("status"),
                    }
                    for item in purchase_request_items[:FOCUS_LIMIT]
                ],
            }
        if can_view_products:
            focus_panels["products_missing_image"] = {
                "title": "Товары без изображений",
                "description": "Активные карточки товаров, где не хватает медиа для продаж.",
                "items": [
                    {
                        "title": product.name,
                        "meta": getattr(product.category, "name", ""),
                        "badge": "Нет изображения",
                        "url": self._admin_change_url(product),
                    }
                    for product in products_without_images[:FOCUS_LIMIT]
                ],
            }
            focus_panels["products_missing_price"] = {
                "title": "Товары без цены",
                "description": "Активные карточки товаров без цены и без режима «цена по запросу».",
                "items": [
                    {
                        "title": product.name,
                        "meta": getattr(product.category, "name", ""),
                        "badge": "Нет цены",
                        "url": self._admin_change_url(product),
                    }
                    for product in products_without_prices[:FOCUS_LIMIT]
                ],
            }
        if can_view_products and can_view_stocks:
            focus_panels["stock_low"] = {
                "title": "Проблемы с остатками",
                "description": "Физические товары без остатков или с критически низким запасом.",
                "items": [
                    {
                        "title": product.name,
                        "meta": getattr(product.category, "name", ""),
                        "badge": f"Остаток: {product.stock_total}",
                        "url": self._admin_change_url(product),
                    }
                    for product in [*out_of_stock_products, *low_stock_products][:FOCUS_LIMIT]
                ],
            }

        summary = []
        if can_view_orders:
            summary.append(
                {
                    "label": "Новые заказы",
                    "value": new_orders_count,
                    "note": "Ожидают обработки менеджером",
                    "url": self._index_url(focus="orders_new"),
                }
            )
        if can_view_leads:
            summary.append(
                {
                    "label": "Новые заявки",
                    "value": lead_count_24h,
                    "note": "За последние 24 часа",
                    "url": self._index_url(focus="leads_recent"),
                }
            )
        if can_view_purchase_requests:
            summary.append(
                {
                    "label": "Заявки на покупку",
                    "value": purchase_request_count,
                    "note": "Новые входящие обращения",
                    "url": self._index_url(focus="purchase_requests_new"),
                }
            )
        if can_view_products:
            summary.append(
                {
                    "label": "Карточки с проблемами",
                    "value": product_issue_count,
                    "note": "Нет цены или изображения",
                    "url": self._index_url(focus="products_missing_price"),
                }
            )
        if can_view_stocks:
            summary.append(
                {
                    "label": "Проблемы с остатками",
                    "value": stock_issue_count,
                    "note": "Нужна поставка или корректировка",
                    "url": self._index_url(focus="stock_low"),
                }
            )

        today_attention = []
        if can_view_orders:
            today_attention.append(
                {
                    "title": "Подтвердить новые заказы",
                    "count": new_orders_count,
                    "description": "Откройте входящие заказы и зафиксируйте следующий шаг.",
                    "url": self._index_url(focus="orders_new"),
                }
            )
        if can_view_leads:
            today_attention.append(
                {
                    "title": "Связаться с новыми лидами",
                    "count": lead_count_24h,
                    "description": "Ответьте по контактам, звонкам и заявкам VR-клубов.",
                    "url": self._index_url(focus="leads_recent"),
                }
            )
        if can_view_purchase_requests:
            today_attention.append(
                {
                    "title": "Разобрать заявки на покупку",
                    "count": purchase_request_count,
                    "description": "Новые запросы на подбор и расчёт оборудования.",
                    "url": self._index_url(focus="purchase_requests_new"),
                }
            )
        if can_view_products:
            today_attention.append(
                {
                    "title": "Дозаполнить карточки товаров",
                    "count": product_issue_count,
                    "description": "Найдите товары без цены и визуала до публикации.",
                    "url": self._index_url(focus="products_missing_image"),
                }
            )
        if can_view_stocks:
            today_attention.append(
                {
                    "title": "Проверить остатки",
                    "count": stock_issue_count,
                    "description": "Товары закончились или близки к нулю.",
                    "url": self._index_url(focus="stock_low"),
                }
            )

        quick_actions = []
        if self._can_add_model(request, Order):
            quick_actions.append({"label": "Новый заказ", "url": self._admin_add_url(Order)})
        if self._can_add_model(request, Product):
            quick_actions.append({"label": "Новый товар", "url": self._admin_add_url(Product)})
        if request.user.is_staff:
            quick_actions.append({"label": "Приход на склад", "url": reverse("admin:warehouse_ui_index")})
        if self._can_add_model(request, ContractDocument):
            quick_actions.append({"label": "Создать договор", "url": self._admin_add_url(ContractDocument)})
        if self._can_add_model(request, ManagerClient):
            quick_actions.append({"label": "Добавить клиента", "url": self._admin_add_url(ManagerClient)})

        task_center = []
        if can_view_orders:
            task_center.append(
                {
                    "title": "Новые заказы",
                    "count": new_orders_count,
                    "url": self._index_url(focus="orders_new"),
                    "empty": "Новых заказов без обработки нет.",
                    "items": order_items,
                }
            )
        if can_view_leads:
            task_center.append(
                {
                    "title": "Новые заявки",
                    "count": lead_count_24h,
                    "url": self._index_url(focus="leads_recent"),
                    "empty": "Новых заявок за последние 24 часа нет.",
                    "items": lead_items[:6],
                }
            )
        if can_view_purchase_requests:
            task_center.append(
                {
                    "title": "Заявки на покупку",
                    "count": purchase_request_count,
                    "url": self._index_url(focus="purchase_requests_new"),
                    "empty": "Новых заявок на покупку нет.",
                    "items": purchase_request_items,
                }
            )
        if can_view_products:
            task_center.append(
                {
                    "title": "Карточки без цены или изображения",
                    "count": product_issue_count,
                    "url": self._index_url(focus="products_missing_price"),
                    "empty": "Критичных проблем в карточках товаров не найдено.",
                    "items": unique_product_issue_preview[:6],
                }
            )
        if can_view_products and can_view_stocks:
            task_center.append(
                {
                    "title": "Складские риски",
                    "count": stock_issue_count,
                    "url": self._index_url(focus="stock_low"),
                    "empty": "Критичных проблем с остатками не найдено.",
                    "items": unique_stock_issue_preview[:6],
                }
            )

        focus_key = (request.GET.get("focus") or "").strip()
        focus_panel = focus_panels.get(focus_key)

        return {
            "summary": summary,
            "today_attention": today_attention,
            "quick_actions": quick_actions,
            "task_center": task_center,
            "focus_panel": focus_panel,
        }
