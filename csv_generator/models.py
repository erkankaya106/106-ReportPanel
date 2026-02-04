from django.db import models

from csv_generator.enums import TypeChoices

class CSVJob(models.Model):
    row_count = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CSV Job #{self.id}"


class CSVJobColumn(models.Model):

    TYPE_CHOICES = [
        ("string", "String"),
        ("int", "Integer"),
        ("date", "Date"),
        ("datetime", "Datetime"),
    ]

    job = models.ForeignKey(
        CSVJob,
        related_name="columns",
        on_delete=models.CASCADE
    )

    name = models.CharField(max_length=50)
    type = models.CharField(max_length=10, choices=TypeChoices , default=TypeChoices.STRING)


    example_value = models.CharField(
        max_length=200,
        help_text="Örn: user{i}@mail.com, 25, 2024-01-01"
    )

    def __str__(self):
        return self.name
