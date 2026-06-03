from django.core.management.base import BaseCommand

from integrations.site_forms import PUBLIC_SITE_FORMS


class Command(BaseCommand):
    help = 'Показывает публичные формы сайта, их поля и текущий pipeline.'

    def handle(self, *args, **options):
        for form_meta in PUBLIC_SITE_FORMS:
            fields = ', '.join(form_meta['fields'])
            self.stdout.write(f"Endpoint: {form_meta['endpoint']}")
            self.stdout.write(f"  Form: {form_meta['form']}")
            self.stdout.write(f"  Template: {form_meta['template']}")
            self.stdout.write(f"  Source type: {form_meta['source_type']}")
            self.stdout.write(f"  Fields: {fields}")
            self.stdout.write(f"  Destination: {form_meta['destination']}")
            self.stdout.write(f"  Creates order: {'yes' if form_meta['creates_order'] else 'no'}")
            self.stdout.write(f"  Email notification: {'yes' if form_meta['email_notification'] else 'no'}")
            self.stdout.write(f"  Anti-spam: {'yes' if form_meta['anti_spam'] else 'no'}")
            self.stdout.write('')
