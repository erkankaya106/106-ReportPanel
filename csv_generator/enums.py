from django.db import models
from django.utils.translation import gettext_lazy as _

class TypeChoices(models.TextChoices):
    STRING = "string", _("String")
    INTEGER = "int", _("Integer")
    DATE = "date", _("Date")
    DATETIME = "datetime", _("Datetime")