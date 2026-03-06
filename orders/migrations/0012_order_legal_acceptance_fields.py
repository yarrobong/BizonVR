# Generated manually for order legal acceptance fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0011_purchaserequest_legal_acceptance_ip_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='legal_acceptance_ip',
            field=models.GenericIPAddressField(blank=True, null=True, verbose_name='IP при согласии'),
        ),
        migrations.AddField(
            model_name='order',
            name='legal_acceptance_user_agent',
            field=models.CharField(blank=True, max_length=512, verbose_name='User-Agent при согласии'),
        ),
        migrations.AddField(
            model_name='order',
            name='legal_accepted_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Согласие с юр. документами'),
        ),
        migrations.AddField(
            model_name='order',
            name='legal_docs_version',
            field=models.CharField(blank=True, max_length=32, verbose_name='Версия юр. документов'),
        ),
    ]
