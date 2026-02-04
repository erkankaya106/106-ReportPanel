from django.contrib import admin
from django.urls import path
from django.shortcuts import get_object_or_404

from .models import CSVJob, CSVJobColumn
from .services import export_csv
from django.utils.html import format_html

class CSVJobColumnInline(admin.TabularInline):
    model = CSVJobColumn
    extra = 1


@admin.register(CSVJob)
class CSVJobAdmin(admin.ModelAdmin):
    list_display = ("id", "row_count", "export_button")
    inlines = [CSVJobColumnInline]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:job_id>/export/",
                self.admin_site.admin_view(self.export_csv_view),
                name="csvjob-export",
            ),
        ]
        return custom_urls + urls

    def export_csv_view(self, request, job_id):
        job = get_object_or_404(CSVJob, pk=job_id)
        return export_csv(job)

    def export_button(self, obj):
        return format_html(
            '<a class="button" href="{}">CSV ÜRET</a>',
            f"{obj.id}/export/"
        )

