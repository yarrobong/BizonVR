from django.contrib.admin import AdminSite


# Логические группы для главной страницы админ-панели.
# Ключ — название группы, значение — список model object_name в нужном порядке.
ADMIN_GROUPS = [
    (
        "Каталог",
        [
            "Product",
            "ProductVariant",
            "ProductBundle",
            "ProductContentBlock",
            "CatalogSection",
            "Category",
            "ProductTag",
        ],
    ),
    (
        "Характеристики и фильтры",
        [
            "CharacteristicDefinition",
            "CharacteristicSourceAlias",
            "CharacteristicValueAlias",
            "FilterConfig",
        ],
    ),
    (
        "Заказы и оплата",
        [
            "Order",
            "OrderItem",
            "PromoCode",
            "PurchaseRequest",
            "Payment",
            "OrderNotificationLog",
        ],
    ),
    (
        "CRM и сделки",
        [
            "ManagerClient",
            "ManagerDeal",
            "DealActivity",
            "DealSavedView",
            "TradeInItem",
            "Reservation",
        ],
    ),
    (
        "Склад и логистика",
        [
            "Warehouse",
            "InventoryBalance",
            "InventoryMovement",
            "InventoryLot",
            "SaleLineAllocation",
            "Purchase",
            "Cargo",
            "TransportLeg",
            "Expense",
            "City",
            "PickupPoint",
            "ProductStock",
        ],
    ),
    (
        "Финансы",
        [
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
        "Договоры",
        [
            "ContractDocument",
            "ContractTemplate",
            "ContractCompanyProfile",
        ],
    ),
    (
        "Поддержка",
        [
            "ContactRequest",
            "CallbackRequest",
            "CartItem",
            "Service",
            "Favorite",
        ],
    ),
    (
        "Пользователи",
        [
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
