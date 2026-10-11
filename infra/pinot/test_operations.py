import copy
import json
from pathlib import Path
import unittest

from provision import verify_table
from provision_operations import verify_operations_schema
from smoke_test_operations import build_events, verify_rows


class OperationsTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent
        self.schema = json.loads((root / 'operations-schema.json').read_text())
        self.table = json.loads((root / 'operations-realtime-table.json').read_text())

    def test_matching_resources(self):
        verify_operations_schema(copy.deepcopy(self.schema), self.schema)
        verify_table({'REALTIME': copy.deepcopy(self.table)}, self.table)

    def test_disabled_null_handling_rejected(self):
        actual = copy.deepcopy(self.schema)
        actual['enableColumnBasedNullHandling'] = False
        with self.assertRaisesRegex(RuntimeError, 'null handling'):
            verify_operations_schema(actual, self.schema)

    def test_wrong_topic_rejected(self):
        actual = copy.deepcopy(self.table)
        actual['ingestionConfig']['streamIngestionConfig']['streamConfigMaps'][0]['stream.kafka.topic.name'] = 'ride-metrics-snapshots'
        with self.assertRaisesRegex(RuntimeError, 'ingestion configuration differs'):
            verify_table({'REALTIME': actual}, self.table)

    def test_smoke_rejects_duplicate_rows(self):
        events = build_events('test-run', 123)
        with self.assertRaisesRegex(AssertionError, 'Expected 10 rows'):
            verify_rows(events + [events[0]], events)

    def test_smoke_rejects_null_replaced_by_default(self):
        events = build_events('test-run', 123)
        rows = copy.deepcopy(events)
        rows[0]['user_id'] = 'null'
        with self.assertRaisesRegex(AssertionError, 'Event mismatch'):
            verify_rows(rows, events)


if __name__ == '__main__':
    unittest.main()
