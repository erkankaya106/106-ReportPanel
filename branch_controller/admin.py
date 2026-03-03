from datetime import date, timedelta

from django import forms
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.utils.html import format_html

from .models import Bayi, TransferLog, CSVValidationError


# ── Bayi ─────────────────────────────────────────────────────────────────────

@admin.register(Bayi)
class BayiAdmin(admin.ModelAdmin):
    list_display = ('name', 'branch_id', 'is_active', 'created_at')
    search_fields = ('name', 'branch_id')
    actions = ['regenerate_secret_keys']
    
    fieldsets = (
        ('Temel Bilgiler', {
            'fields': ('name', 'branch_id', 'is_active')
        }),
        ('Secret Key', {
            'fields': ('secret_key_display', '_temp_secret_key_display'),
            'description': 'Secret key güvenlik nedeniyle hash\'lenmiş olarak saklanır. Yeni key üretmek için action kullanın.'
        }),
        ('Tarih Bilgileri', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('secret_key_display', '_temp_secret_key_display', 'created_at')
    
    def get_fieldsets(self, request, obj=None):
        """Yeni kayıt için fieldsets'i özelleştir."""
        if obj is None:  # Yeni kayıt
            return (
                ('Temel Bilgiler', {
                    'fields': ('name', 'branch_id', 'is_active')
                }),
                ('Secret Key', {
                    'fields': ('_temp_secret_key_display',),
                    'description': 'Secret key otomatik üretilecek ve gösterilecektir. Lütfen not edin!'
                }),
            )
        return super().get_fieldsets(request, obj)
    
    def secret_key_display(self, obj):
        """Secret key'i hash'lenmiş halde göster (Django password field gibi)."""
        if not obj or not obj.secret_key:
            return "Secret key henüz oluşturulmamış"
        
        # Encrypt edilmiş halini göster (ilk birkaç karakter + ...)
        if len(obj.secret_key) > 20:
            display = obj.secret_key[:20] + "..."
        else:
            display = obj.secret_key
        
        return format_html(
            '<code style="font-family: monospace; color: #666;">{}</code>',
            display
        )
    secret_key_display.short_description = 'Secret Key (Hash\'lenmiş)'
    
    def _temp_secret_key_display(self, obj):
        """Yeni üretilen secret key'i göster (sadece doluysa)."""
        if not obj:
            # Yeni kayıt için otomatik üretilecek mesajı
            return format_html(
                '<div style="color: #d9534f; font-weight: bold; padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px;">'
                '⚠️ Secret key kayıt sırasında otomatik üretilecek ve burada gösterilecektir. '
                'Lütfen not edin, bir daha gösterilmeyecek!'
                '</div>'
            )
        
        if obj._temp_secret_key:
            return format_html(
                '<div style="color: #d9534f; font-weight: bold; padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; margin: 10px 0;">'
                '⚠️ <strong>YENİ SECRET KEY ÜRETİLDİ - LÜTFEN NOT EDİN!</strong><br>'
                '<code style="font-family: monospace; font-size: 14px; background: white; padding: 5px; display: block; margin-top: 5px;">{}</code>'
                '<small style="display: block; margin-top: 5px;">Bu key kayıt sonrası hash\'lenecek ve bir daha gösterilmeyecek!</small>'
                '</div>',
                obj._temp_secret_key
            )
        return "Secret key hash'lenmiş olarak saklanıyor (güvenlik nedeniyle gösterilemez)"
    _temp_secret_key_display.short_description = 'Yeni Secret Key'

    def save_model(self, request, obj, form, change):
        """Save işlemi sırasında secret key'i yönet."""
        # İlk kayıt: secret_key boşsa otomatik üret
        if not change and not obj.secret_key and not obj._temp_secret_key:
            obj._temp_secret_key = Bayi.generate_secret_key()
        
        # _temp_secret_key'i session'a kaydet (response'da göstermek için)
        temp_key = obj._temp_secret_key
        if temp_key:
            if not hasattr(request.session, 'new_secret_keys'):
                request.session['new_secret_keys'] = {}
            request.session['new_secret_keys'][str(obj.pk) if obj.pk else 'new'] = temp_key
        
        # Save işlemini yap
        super().save_model(request, obj, form, change)
        
        # Save sonrası obj'yi yeniden yükle (DB'den güncel halini al)
        if obj.pk:
            obj.refresh_from_db()
            # Memory'de _temp_secret_key'i koru (response'da gösterilmek için)
            if temp_key:
                obj._temp_secret_key = temp_key
    
    def response_add(self, request, obj, post_url_continue=None):
        """Yeni kayıt sonrası response."""
        response = super().response_add(request, obj, post_url_continue)
        
        # Session'dan _temp_secret_key'i al ve göster
        new_secret_keys = request.session.get('new_secret_keys', {})
        temp_key = new_secret_keys.get('new') or (hasattr(obj, '_temp_secret_key') and obj._temp_secret_key)
        
        if temp_key:
            self.message_user(
                request,
                format_html(
                    '<div style="color: #d9534f; font-weight: bold; padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; margin: 10px 0;">'
                    '⚠️ <strong>YENİ SECRET KEY ÜRETİLDİ - LÜTFEN NOT EDİN!</strong><br>'
                    '<code style="font-family: monospace; font-size: 14px; background: white; padding: 5px; display: block; margin-top: 5px;">{}</code>'
                    '<small style="display: block; margin-top: 5px;">Bu key kayıt sonrası hash\'lenecek ve bir daha gösterilmeyecek!</small>'
                    '</div>',
                    temp_key
                ),
                level='warning'
            )
            # Session'dan temizle
            if 'new_secret_keys' in request.session:
                del request.session['new_secret_keys']['new']
                if not request.session['new_secret_keys']:
                    del request.session['new_secret_keys']
        
        return response
    
    def response_change(self, request, obj):
        """Kayıt güncelleme sonrası response."""
        response = super().response_change(request, obj)
        
        # Session'dan _temp_secret_key'i al ve göster
        new_secret_keys = request.session.get('new_secret_keys', {})
        temp_key = None
        if obj.pk:
            temp_key = new_secret_keys.get(str(obj.pk)) or (hasattr(obj, '_temp_secret_key') and obj._temp_secret_key)
        
        if temp_key:
            self.message_user(
                request,
                format_html(
                    '<div style="color: #d9534f; font-weight: bold; padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; margin: 10px 0;">'
                    '⚠️ <strong>YENİ SECRET KEY ÜRETİLDİ - LÜTFEN NOT EDİN!</strong><br>'
                    '<code style="font-family: monospace; font-size: 14px; background: white; padding: 5px; display: block; margin-top: 5px;">{}</code>'
                    '<small style="display: block; margin-top: 5px;">Bu key kayıt sonrası hash\'lenecek ve bir daha gösterilmeyecek!</small>'
                    '</div>',
                    temp_key
                ),
                level='warning'
            )
            # Session'dan temizle
            if obj.pk and 'new_secret_keys' in request.session:
                if str(obj.pk) in request.session['new_secret_keys']:
                    del request.session['new_secret_keys'][str(obj.pk)]
                if not request.session['new_secret_keys']:
                    del request.session['new_secret_keys']
        
        return response

    def regenerate_secret_keys(self, request, queryset):
        """Seçili bayiler için secret key'i yeniden oluştur."""
        updated_count = 0
        new_keys = []
        
        for bayi in queryset:
            new_key = Bayi.generate_secret_key()
            # _temp_secret_key'e kaydet, save() metodu bunu encrypt ederek secret_key'e kaydedecek
            bayi._temp_secret_key = new_key
            bayi.save()
            new_keys.append(f"{bayi.name} ({bayi.branch_id}): {new_key}")
            updated_count += 1

        message = format_html(
            '<div style="color: #d9534f; font-weight: bold; padding: 10px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px;">'
            '<strong>{} bayinin secret key\'i yeniden oluşturuldu:</strong><br>'
            '<pre style="background: white; padding: 10px; margin-top: 10px; overflow-x: auto;">{}</pre>'
            '<small>⚠️ Lütfen bu key\'leri not edin, bir daha gösterilmeyecek!</small>'
            '</div>',
            updated_count,
            '\n'.join(new_keys)
        )
        self.message_user(request, message, level='warning')

    regenerate_secret_keys.short_description = (
        "Seçili bayiler için secret key'i yeniden oluştur"
    )


# ── TransferLog ───────────────────────────────────────────────────────────────

@admin.register(TransferLog)
class TransferLogAdmin(admin.ModelAdmin):
    list_display = ('bayi', 'filename', 'status', 'created_at', 'ip_address')
    list_filter = ('status', 'bayi')
    readonly_fields = (
        'bayi', 'filename', 's3_path', 'status', 'error_message', 'ip_address', 'created_at'
    )

    def has_add_permission(self, request):
        return False


# ── CSVValidationError ────────────────────────────────────────────────────────

class ValidationDateFilter(SimpleListFilter):
    """
    validation_date alanı için Bugün / Dün / Tarih seç hızlı filtreleri.
    Tarih seçimi date_hierarchy üzerinden de yapılabilir.
    """
    title = "CSV Tarihi"
    parameter_name = "vdate"

    def lookups(self, request, model_admin):
        today = date.today()
        yesterday = today - timedelta(days=1)
        return [
            ("today",     f"Bugün ({today.strftime('%d.%m.%Y')})"),
            ("yesterday", f"Dün ({yesterday.strftime('%d.%m.%Y')})"),
            ("this_week", "Bu Hafta"),
            ("this_month", "Bu Ay"),
        ]

    def queryset(self, request, queryset):
        today = date.today()
        if self.value() == "today":
            return queryset.filter(validation_date=today)
        if self.value() == "yesterday":
            return queryset.filter(validation_date=today - timedelta(days=1))
        if self.value() == "this_week":
            week_start = today - timedelta(days=today.weekday())
            return queryset.filter(validation_date__gte=week_start, validation_date__lte=today)
        if self.value() == "this_month":
            return queryset.filter(
                validation_date__year=today.year,
                validation_date__month=today.month,
            )
        return queryset


@admin.register(CSVValidationError)
class CSVValidationErrorAdmin(admin.ModelAdmin):
    list_display = (
        'filename',
        'provider_id',
        'accuracy_display',
        'error_count',
        'total_rows',
        'bayi',
        'validation_date',
        'detected_at',
    )
    list_filter = (
        ValidationDateFilter,   # Bugün / Dün / Bu Hafta / Bu Ay
        'bayi',
        'filename',             # bet.csv / win.csv / canceled.csv
    )
    search_fields = ('filename', 'summary_message', 'bayi__branch_id', 'bayi__name')
    readonly_fields = (
        'bayi',
        'filename',
        'provider_id',
        'validation_date',
        'total_rows',
        'error_count',
        'accuracy_rate',
        'error_summary_display',
        'summary_message',
        'detected_at',
    )
    # date_hierarchy üzerinden yıl/ay/gün bazında tarihe göre drill-down
    date_hierarchy = 'validation_date'

    def accuracy_display(self, obj):
        """Doğruluk oranını renkli göster"""
        rate = float(obj.accuracy_rate)
        if rate == 100.0:
            color, icon = 'green', '✓'
        elif rate >= 80.0:
            color, icon = 'green', '○'
        elif rate >= 50.0:
            color, icon = 'orange', '△'
        else:
            color, icon = 'red', '✗'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{} %{}</span>',
            color, icon, f'{rate:.2f}'
        )

    accuracy_display.short_description = 'Doğruluk'
    accuracy_display.admin_order_field = 'accuracy_rate'

    def error_summary_display(self, obj):
        """Error summary'yi güzel formatla"""
        if not obj.error_summary:
            return "Hata yok"

        html_parts = []
        for error_type, details in obj.error_summary.items():
            total_count = sum(d['count'] for d in details.values())
            html_parts.append(f"<b>{error_type}</b>: {total_count} adet")

        return format_html('<br>'.join(html_parts))

    error_summary_display.short_description = 'Hata Özeti'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
