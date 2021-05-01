from galaxy.model.migrate.versions.util import execute_statements


# function name prefix
fn_prefix = "fn_audit_history_by"

# map between source table and associated incoming id field
trigger_config = {
    'history_dataset_association': "history_id",
    'history_dataset_collection_association': "history_id",
    'history': "id",
}


def install(engine):
    """Install history audit table triggers"""
    sql = _postgres_install() if 'postgres' in engine.name else _sqlite_install()
    execute_statements(engine, sql)


def remove(engine):
    """Uninstall history audit table triggers"""
    sql = _postgres_remove() if 'postgres' in engine.name else _sqlite_remove()
    execute_statements(engine, sql)


# Postgres trigger installation


def _postgres_remove():
    """postgres trigger removal sql"""

    sql = []
    sql.append(f"DROP FUNCTION IF EXISTS {fn_prefix}_history_id() CASCADE;")
    sql.append(f"DROP FUNCTION IF EXISTS {fn_prefix}_id() CASCADE;")

    return sql


def _postgres_install():
    """postgres trigger installation sql"""

    sql = []

    # postgres trigger function template
    # need to make separate functions purely because the incoming history_id field name will be
    # different for different source tables. There may be a fancier way to dynamically choose
    # between incoming fields, but having 2 triggers fns seems straightforward

    def trigger_fn(id_field):
        fn = f"{fn_prefix}_{id_field}"

        return f"""
            CREATE OR REPLACE FUNCTION {fn}()
                RETURNS TRIGGER
                LANGUAGE 'plpgsql'
            AS $BODY$
                BEGIN
                    INSERT INTO history_audit (history_id, update_time)
                    SELECT {id_field}, CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                    FROM new_table
                    WHERE {id_field} IS NOT NULL;
                    RETURN NULL;
                END;
            $BODY$
        """

    def trigger_def(source_table, id_field, operation, when="AFTER"):
        fn = f"{fn_prefix}_{id_field}"

        # Postgres supports many triggers per operation/table so the label can
        # be indicative of what's happening
        label = f"history_audit_by_{id_field}"
        trigger_name = get_trigger_name(label, operation, when, statement=True)

        return f"""
            CREATE TRIGGER {trigger_name}
            {when} {operation} ON {source_table}
            REFERENCING NEW TABLE AS new_table
            FOR EACH STATEMENT EXECUTE FUNCTION {fn}();
        """

    # trigger functions, each reads a different incoming id
    for id_field in ["history_id", "id"]:
        sql.append(trigger_fn(id_field))

    # add triggers for each configured table (history, hda, hdca)
    # picking the appropriate function via the config
    for source_table, id_field in trigger_config.items():
        for operation in ["UPDATE", "INSERT"]:
            sql.append(trigger_def(source_table, id_field, operation))

    return sql


# Other DBs


def _sqlite_remove():
    sql = []

    for source_table in trigger_config:
        for operation in ["UPDATE", "INSERT"]:
            trigger_name = get_trigger_name(source_table, operation, "AFTER")
            sql.append(f"DROP TRIGGER IF EXISTS {trigger_name};")

    return sql


def _sqlite_install():
    # delete old stuff first
    sql = _sqlite_remove()

    def trigger_def(source_table, id_field, operation, when="AFTER"):

        # only one trigger per operation/table in simple databases, so
        # trigger name is less descriptive
        trigger_name = get_trigger_name(source_table, operation, when)

        return f"""
            CREATE TRIGGER {trigger_name}
                {when} {operation}
                ON {source_table}
                FOR EACH ROW
                BEGIN
                    INSERT INTO history_audit (history_id, update_time)
                    SELECT NEW.{id_field}, CURRENT_TIMESTAMP
                    WHERE NEW.{id_field} IS NOT NULL;
                END;
        """

    for source_table, id_field in trigger_config.items():
        for operation in ["UPDATE", "INSERT"]:
            sql.append(trigger_def(source_table, id_field, operation))

    return sql


# Utils


def get_trigger_name(label, operation, when, statement=False):
    op_initial = operation.lower()[0]
    when_initial = when.lower()[0]
    rs = "s" if statement else "r"
    return f"trigger_{label}_{when_initial}{op_initial}{rs}"
