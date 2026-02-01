# Generated manually: заполнить referral_code и сделать поле unique

import uuid
from django.db import migrations, models


def generate_code():
    return uuid.uuid4().hex[:10].lower()


def fill_referral_codes(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    used = set()
    for p in Profile.objects.all():
        if not p.referral_code or p.referral_code in used:
            while True:
                code = generate_code()
                if code not in used:
                    break
            p.referral_code = code
            p.save(update_fields=['referral_code'])
            used.add(code)
        else:
            used.add(p.referral_code)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_balancetransaction_order_balancetransaction_referral_and_more'),
    ]

    operations = [
        migrations.RunPython(fill_referral_codes, noop),
        migrations.AlterField(
            model_name='profile',
            name='referral_code',
            field=models.CharField(blank=True, db_index=True, max_length=20, unique=True, verbose_name='Реферальный код'),
        ),
    ]
