from django.core.management.base import BaseCommand, CommandError

from manager_portal.single_db_contract import collect_single_db_contract_violations


class Command(BaseCommand):
    help = 'Validate that BizonVR uses a single active PostgreSQL runtime and no active secondary DBs.'

    def handle(self, *args, **options):
        violations = collect_single_db_contract_violations()
        if violations:
            for violation in violations:
                self.stderr.write(f'- {violation}')
            raise CommandError('Single-DB contract violated.')
        self.stdout.write(self.style.SUCCESS('Single-DB contract is satisfied.'))
