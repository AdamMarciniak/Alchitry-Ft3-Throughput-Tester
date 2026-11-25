"""Load the deliverable presets through the actual Qt host in simulation only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'host'))
from test_rf_debug_ui import HostTests
from rf_debug import atomic_json, load_settings, validate_settings

HostTests.setUpClass()  # Explicit 'sim' before host import; no USB opened.
case = HostTests()
case.setUp()
results = []
try:
    assert not case.h.HW
    values = {}
    for name in ['heart-recording-baseline', 'heart-review-start', 'heart-tgc-next-test']:
        expected = load_settings(ROOT / 'host/presets' / (name + '.json'))
        values[name] = expected
        case.w.debug_apply(expected)
        case.w.debug_tick()
        actual = validate_settings(case.h.settings_snapshot(case.w))
        for section, fields in expected.items():
            for key, value in fields.items():
                assert actual[section][key] == value, (name, section, key, value, actual[section][key])
        assert not case.h.pulser.arm
        assert not case.w.cb_arm.isChecked()
        results.append({'preset': name, 'restored_operational_fields': True, 'armed': False})
    a, b = values['heart-recording-baseline'], values['heart-tgc-next-test']
    diff = [f'{s}.{k}' for s in a for k in a[s] if a[s][k] != b[s][k]]
    assert sorted(diff) == ['acquisition.tgc_max', 'acquisition.tgc_min'], diff
    atomic_json(Path(__file__).parent / 'preset-validation.json', {
        'source': 'simulation; no hardware opened', 'presets': results,
        'tgc_comparison_changed_fields': diff})
    print('Three presets restored exactly and disarmed; TGC comparison changes only its two endpoints.')
finally:
    case.tearDown()
