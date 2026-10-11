"""Create the v2 table without updating v1 or replacing existing resources."""
import json

from provision import ROOT, compose, controller, verify_schema, verify_table


def verify_operations_schema(actual, expected):
    if actual.get('schemaName') != 'operations' or not actual.get('enableColumnBasedNullHandling'):
        raise RuntimeError('Existing operations schema must enable column-based null handling.')
    verify_schema(actual, expected)


def main():
    expected_schema = json.loads((ROOT / 'infra/pinot/operations-schema.json').read_text())
    expected_table = json.loads((ROOT / 'infra/pinot/operations-realtime-table.json').read_text())
    schema = controller('schemas/operations')
    table = controller('tables/operations')
    if schema is not None:
        verify_operations_schema(schema, expected_schema)
    if table is not None:
        if schema is None:
            raise RuntimeError('operations table exists without its schema.')
        verify_table(table, expected_table)
        print('Existing operations schema and REALTIME table match; no changes made.')
        return
    print(compose('exec', '-T', 'pinot-controller', '/opt/pinot/bin/pinot-admin.sh',
                  'AddTable', '-schemaFile', '/config/operations-schema.json',
                  '-tableConfigFile', '/config/operations-realtime-table.json',
                  '-controllerHost', 'pinot-controller', '-controllerPort', '9000',
                  '-exec'), end='')
    verify_operations_schema(controller('schemas/operations'), expected_schema)
    verify_table(controller('tables/operations'), expected_table)


if __name__ == '__main__':
    main()
