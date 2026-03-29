from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('manager_portal', '0018_inventorylot_salelineallocation_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(
                    model_name='financedeal',
                    name='cost_price',
                ),
                migrations.RemoveField(
                    model_name='financedeal',
                    name='margin',
                ),
                migrations.RemoveField(
                    model_name='financedeal',
                    name='expected_margin_snapshot',
                ),
                migrations.AddField(
                    model_name='financedeal',
                    name='cost_of_goods',
                    field=models.DecimalField(
                        db_column='cost_price',
                        decimal_places=2,
                        default=Decimal('0'),
                        max_digits=14,
                        verbose_name='Закуп / себестоимость',
                    ),
                ),
                migrations.AddField(
                    model_name='financedeal',
                    name='distributable_profit',
                    field=models.DecimalField(
                        db_column='margin',
                        decimal_places=2,
                        default=Decimal('0'),
                        max_digits=14,
                        verbose_name='Распределяемая прибыль',
                    ),
                ),
                migrations.AddField(
                    model_name='financedeal',
                    name='expected_distributable_profit_snapshot',
                    field=models.DecimalField(
                        db_column='expected_margin_snapshot',
                        decimal_places=2,
                        default=Decimal('0'),
                        max_digits=14,
                        verbose_name='Ожидаемая распределяемая прибыль сделки',
                    ),
                ),
            ],
        ),
        migrations.AddField(
            model_name='financedealline',
            name='replacement_of',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='replacement_lines',
                to='manager_portal.financedealline',
                verbose_name='Замена для строки',
            ),
        ),
        migrations.AddField(
            model_name='financeexpense',
            name='finance_line',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='expenses',
                to='manager_portal.financedealline',
                verbose_name='Строка сделки',
            ),
        ),
        migrations.AddField(
            model_name='financeexpense',
            name='affects_direct_expenses',
            field=models.BooleanField(
                blank=True,
                default=None,
                null=True,
                verbose_name='Учитывать в прямых расходах',
            ),
        ),
        migrations.AddField(
            model_name='financeexpense',
            name='refund_policy',
            field=models.CharField(
                choices=[
                    ('non_refundable', 'Не возвращается'),
                    ('proportional_to_reversal', 'Пропорционально развороту'),
                    ('on_full_reversal', 'Только при полном развороте'),
                ],
                db_index=True,
                default='non_refundable',
                max_length=40,
                verbose_name='Политика возврата',
            ),
        ),
        migrations.CreateModel(
            name='FinanceDealAdjustment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('adjustment_kind', models.CharField(choices=[('shipment_return', 'Возврат после отгрузки'), ('shipment_cancellation', 'Отмена до отгрузки'), ('replacement_reversal', 'Разворот заменяемой строки'), ('replacement_addition', 'Добавление строки замены'), ('direct_expense_refund', 'Возврат прямого расхода'), ('manual_correction', 'Ручная корректировка')], db_index=True, max_length=40, verbose_name='Тип корректировки')),
                ('reason_code', models.CharField(blank=True, max_length=80, verbose_name='Причина')),
                ('quantity_delta', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Изменение количества')),
                ('revenue_delta', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Изменение выручки')),
                ('cost_of_goods_delta', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Изменение себестоимости')),
                ('direct_expenses_delta', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Изменение прямых расходов')),
                ('manager_bonus_delta', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Изменение бонуса менеджера')),
                ('payload', models.JSONField(blank=True, default=dict, verbose_name='Payload')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Создана')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manager_finance_adjustments', to=settings.AUTH_USER_MODEL, verbose_name='Создал')),
                ('finance_deal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='adjustments', to='manager_portal.financedeal', verbose_name='Финансовая сделка')),
                ('finance_line', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='adjustments', to='manager_portal.financedealline', verbose_name='Строка сделки')),
                ('related_activity', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_adjustments', to='manager_portal.dealactivity', verbose_name='Связанное событие')),
                ('related_document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_adjustments', to='manager_portal.contractdocument', verbose_name='Связанный документ')),
                ('related_expense', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='adjustments', to='manager_portal.financeexpense', verbose_name='Связанный расход')),
                ('related_shipment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='finance_adjustments', to='manager_portal.shipment', verbose_name='Связанная отгрузка')),
            ],
            options={
                'verbose_name': 'Финансы: корректировка',
                'verbose_name_plural': 'Финансы: корректировки',
                'ordering': ['finance_deal_id', '-created_at', '-id'],
            },
        ),
    ]
