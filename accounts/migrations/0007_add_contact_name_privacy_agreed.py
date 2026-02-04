# Generated manually for complete registration flow

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_alter_balancetransaction_kind'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='contact_name',
            field=models.CharField(blank=True, max_length=255, verbose_name='Контактное лицо (ФИО)'),
        ),
        migrations.AddField(
            model_name='profile',
            name='privacy_agreed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Согласие на обработку ПД'),
        ),
    ]
