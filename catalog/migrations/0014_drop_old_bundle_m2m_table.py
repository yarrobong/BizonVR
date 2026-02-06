"""
Явно удалить старую M2M-таблицу catalog_productbundle_products, если она осталась.
Исправляет ошибку: relation "catalog_productbundle_products" does not exist
(когда миграция 0013 удалила поле, но таблица могла остаться в другом состоянии).
"""
from django.db import migrations


def drop_old_m2m_table(apps, schema_editor):
    """Удалить таблицу catalog_productbundle_products если существует."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            DROP TABLE IF EXISTS catalog_productbundle_products CASCADE;
        """)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0013_bundle_explicit_prices'),
    ]

    operations = [
        migrations.RunPython(drop_old_m2m_table, noop),
    ]
