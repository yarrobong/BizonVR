from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_savedaddress'),
    ]

    operations = [
        migrations.AddField(
            model_name='phoneverificationcode',
            name='used_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
