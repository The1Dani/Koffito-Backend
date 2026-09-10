from alembic.autogenerate import renderers
from alembic.operations import MigrateOperation


def enable_rls(op, table_name):
    """Enable Postgres row-level security on a table. No-op on other dialects."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')


class EnableRLS(MigrateOperation):
    """Autogenerate marker that renders a plain call to enable_rls()."""

    def __init__(self, table_name):
        self.table_name = table_name


@renderers.dispatch_for(EnableRLS)
def _render_enable_rls(autogen_context, operation):
    autogen_context.imports.add("from rls import enable_rls")
    return f"enable_rls(op, {operation.table_name!r})"
