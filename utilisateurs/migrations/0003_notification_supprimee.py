from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("utilisateurs", "0002_notification_et_compte_demo"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="supprimee",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["utilisateur", "supprimee"], name="notif_user_supprimee"),
        ),
    ]
