"""Migrate Django tables and protect them from Supabase's public API roles."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import django
from django.apps import apps
from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from psycopg import sql

from config.bootstrap import configure


def main():
    configure()
    if os.environ['DJANGO_SETTINGS_MODULE'] != 'config.production':
        raise SystemExit('Load config.production and the production environment first.')
    django.setup()
    if connection.vendor != 'postgresql':
        raise SystemExit('This command requires PostgreSQL.')

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if any(not migration.atomic for migration, _ in plan):
        raise SystemExit('Non-atomic migrations require a separately reviewed deployment plan.')

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('classlib:migrate'))")
            cursor.execute('SELECT current_schema()')
            if cursor.fetchone()[0] != 'public':
                raise SystemExit('Expected the dedicated ClassLib public schema.')
            cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
            roles = [sql.SQL('PUBLIC')] + [sql.Identifier(row[0]) for row in cursor.fetchall()]
            grantees = sql.SQL(', ').join(roles)
            # Remove both global and schema-specific defaults for the current
            # migration role. New Django tables must not inherit API grants.
            for scope in (sql.SQL(''), sql.SQL(' IN SCHEMA public')):
                for objects in ('TABLES', 'SEQUENCES'):
                    cursor.execute(sql.SQL('ALTER DEFAULT PRIVILEGES{} REVOKE ALL ON {} FROM {}').format(
                        scope, sql.SQL(objects), grantees,
                    ))

        call_command('migrate', interactive=False)
        tables = {
            model._meta.db_table: model._meta.pk.column
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and not model._meta.proxy
        }
        tables['django_migrations'] = 'id'
        present = set(connection.introspection.table_names())
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            for table, pk in sorted(tables.items()):
                if table not in present:
                    continue
                qualified = sql.Identifier('public', table)
                cursor.execute(sql.SQL('ALTER TABLE {} ENABLE ROW LEVEL SECURITY').format(qualified))
                cursor.execute(sql.SQL('REVOKE ALL ON TABLE {} FROM {}').format(qualified, grantees))
                cursor.execute(
                    'SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace '
                    'WHERE c.oid=pg_get_serial_sequence(%s, %s)::regclass',
                    [f'public.{table}', pk],
                )
                sequence = cursor.fetchone()
                if sequence:
                    cursor.execute(sql.SQL('REVOKE ALL ON SEQUENCE {} FROM {}').format(
                        sql.Identifier(*sequence), grantees,
                    ))
        print(f'Protected {len(present.intersection(tables))} Django tables; migration committed atomically.')


if __name__ == '__main__':
    main()
