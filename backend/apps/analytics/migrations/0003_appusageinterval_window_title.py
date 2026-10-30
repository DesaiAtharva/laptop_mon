# Generated migration for AppUsageInterval window_title
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0002_dispute'),
    ]

    operations = [
        migrations.AddField(
            model_name='appusageinterval',
            name='window_title',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Active foreground window or browser tab title.',
                max_length=512,
            ),
        ),
    ]
