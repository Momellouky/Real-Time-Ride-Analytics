"""Provision new resources, or check existing resources without replacing them."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def compose(*args, input=None):
    return subprocess.run(['docker', 'compose', *args], cwd=ROOT, input=input,
                          text=True, capture_output=True, check=True, timeout=60).stdout


def controller(path):
    response = compose('exec', '-T', 'pinot-controller', 'curl', '-sS',
        '--max-time', '10', '-w', '\n%{http_code}', f'http://127.0.0.1:9000/{path}')
    body, code = response.rsplit('\n', 1)
    if code == '404':
        return None
    if code != '200':
        raise RuntimeError(f'Controller {path} returned HTTP {code}: {body}')
    return json.loads(body)


def verify_schema(actual, expected):
    for group in ('dimensionFieldSpecs', 'metricFieldSpecs', 'dateTimeFieldSpecs'):
        fields = {field['name']: field for field in actual.get(group, [])}
        for field in expected[group]:
            if any(fields.get(field['name'], {}).get(key) != value
                   for key, value in field.items()):
                raise RuntimeError(f'Existing schema differs at {field["name"]}; review it in the Controller.')


def verify_table(actual, expected):
    config = actual.get('REALTIME')
    if not config:
        raise RuntimeError('Expected a REALTIME table.')
    for key in ('timeColumnName', 'replicasPerPartition'):
        if config['segmentsConfig'].get(key) != expected['segmentsConfig'][key]:
            raise RuntimeError(f'Existing table differs at {key}; review it in the Controller.')
    for key in ('loadMode', 'invertedIndexColumns', 'rangeIndexColumns'):
        if config['tableIndexConfig'].get(key) != expected['tableIndexConfig'][key]:
            raise RuntimeError(f'Existing table differs at {key}; review it in the Controller.')
    streams = config.get('ingestionConfig', {}).get('streamIngestionConfig', {}).get('streamConfigMaps', [])
    wanted = expected['ingestionConfig']['streamIngestionConfig']['streamConfigMaps']
    if streams != wanted or config.get('upsertConfig') or config.get('dedupConfig'):
        raise RuntimeError('Existing ingestion configuration differs; review it in the Controller.')


def main():
    expected_schema = json.loads((ROOT / 'infra/pinot/ride-metrics-schema.json').read_text())
    expected_table = json.loads((ROOT / 'infra/pinot/ride-metrics-realtime-table.json').read_text())
    topic = compose('exec', '-T', 'kafka', 'printenv', 'KAFKA_TOPIC').strip()
    expected_table['ingestionConfig']['streamIngestionConfig']['streamConfigMaps'][0]['stream.kafka.topic.name'] = topic
    schema = controller('schemas/ride_metrics')
    table = controller('tables/ride_metrics')
    if schema is not None:
        verify_schema(schema, expected_schema)
    if table is not None:
        verify_table(table, expected_table)
        if schema is None:
            raise RuntimeError('Table exists without its schema; review the Controller state.')
        print('Existing ride_metrics schema and REALTIME table match; no changes made.')
        return
    compose('exec', '-T', 'pinot-controller', 'sh', '-c',
            'cat > /tmp/ride-metrics-realtime-table.json', input=json.dumps(expected_table))
    print(compose('exec', '-T', 'pinot-controller', '/opt/pinot/bin/pinot-admin.sh', 'AddTable',
        '-schemaFile', '/config/ride-metrics-schema.json', '-tableConfigFile',
        '/tmp/ride-metrics-realtime-table.json', '-controllerHost', 'pinot-controller',
        '-controllerPort', '9000', '-exec'), end='')
    verify_schema(controller('schemas/ride_metrics'), expected_schema)
    verify_table(controller('tables/ride_metrics'), expected_table)


if __name__ == '__main__':
    main()
