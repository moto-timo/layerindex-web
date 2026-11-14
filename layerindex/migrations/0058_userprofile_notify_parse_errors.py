from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0057_userprofile_previous_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='notify_parse_errors',
            field=models.BooleanField(default=False, help_text='Sent when a layer branch you maintain starts to fail', verbose_name='Email me when my layers fail to parse'),
        ),
    ]
