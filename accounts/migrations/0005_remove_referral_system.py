# Удаление реферальной системы: промо-скидка перенесена в заказы

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_profile_unique_referral_code'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='balancetransaction',
            name='referral',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='referral_code',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='referrer',
        ),
    ]
