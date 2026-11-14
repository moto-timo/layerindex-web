from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0056_layerdependency_from_layer_conf'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='previous_email',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
