import copy
import json
from pathlib import Path
import unittest

from provision import verify_schema, verify_table

CONFIG_DIR = Path(__file__).resolve().parent


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((CONFIG_DIR / 'ride-metrics-schema.json').read_text())
        self.table = json.loads((CONFIG_DIR / 'ride-metrics-realtime-table.json').read_text())

    def test_matching_resources_allow_controller_defaults(self):
        actual = copy.deepcopy(self.table)
        actual['tableName'] += '_REALTIME'
        actual['tenants'] = {'broker': 'DefaultTenant', 'server': 'DefaultTenant'}
        verify_schema(copy.deepcopy(self.schema), self.schema)
        verify_table({'REALTIME': actual}, self.table)

    def test_existing_schema_type_change_is_rejected(self):
        changed = copy.deepcopy(self.schema)
        changed['metricFieldSpecs'][0]['dataType'] = 'LONG'
        with self.assertRaisesRegex(RuntimeError, 'schema differs'):
            verify_schema(changed, self.schema)

    def test_topic_change_does_not_replace_existing_ingestion(self):
        changed = copy.deepcopy(self.table)
        changed['ingestionConfig']['streamIngestionConfig']['streamConfigMaps'][0]['stream.kafka.topic.name'] = 'other-topic'
        with self.assertRaisesRegex(RuntimeError, 'ingestion configuration differs'):
            verify_table({'REALTIME': changed}, self.table)

    def test_upsert_cannot_replace_append_only_storage(self):
        changed = copy.deepcopy(self.table)
        changed['upsertConfig'] = {'mode': 'FULL'}
        with self.assertRaisesRegex(RuntimeError, 'ingestion configuration differs'):
            verify_table({'REALTIME': changed}, self.table)


if __name__ == '__main__':
    unittest.main()
