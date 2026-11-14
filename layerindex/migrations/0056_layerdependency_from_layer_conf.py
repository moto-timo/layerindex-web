from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('layerindex', '0055_recipe_text_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='layerdependency',
            name='from_layer_conf',
            field=models.BooleanField(default=False, verbose_name='From conf/layer.conf'),
        ),
    ]
