import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('window_control', ROOT / 'scripts' / 'window_control.py')
window_control = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(window_control)


class WindowControlTests(unittest.TestCase):
    def test_focus_waits_for_cross_thread_activation(self):
        api = Mock()
        state = {'foreground': 7}
        api.IsIconic.return_value = False
        api.SetForegroundWindow.return_value = True
        api.GetForegroundWindow.side_effect = lambda: state['foreground']

        def process_target_queue(*args):
            state['foreground'] = 42
            return 1

        api.SendMessageTimeoutW.side_effect = process_target_queue
        windows = [{'pid': 10, 'window': 42, 'title': 'Client'}]
        with patch.object(window_control, 'windows_for', return_value=(api, windows)):
            result = window_control.window_focus(Path('client.exe'))
        self.assertTrue(result['ok'])
        self.assertTrue(result['foreground'])
        self.assertEqual(result['business_requests_sent'], 0)

    def test_multiple_windows_require_explicit_selection(self):
        api = Mock()
        windows = [{'pid': 10, 'window': 42, 'title': 'Client'},
                   {'pid': 10, 'window': 43, 'title': 'Dialog'}]
        with patch.object(window_control, 'windows_for', return_value=(api, windows)):
            result = window_control.window_focus(Path('client.exe'))
        self.assertFalse(result['ok'])
        api.SetForegroundWindow.assert_not_called()

    def test_activation_can_finish_after_the_no_op_response(self):
        api = Mock()
        api.IsIconic.return_value = False
        api.SetForegroundWindow.return_value = True
        api.SendMessageTimeoutW.return_value = 1
        api.GetForegroundWindow.side_effect = [7, 42]
        windows = [{'pid': 10, 'window': 42, 'title': 'Client'}]
        with patch.object(window_control, 'windows_for', return_value=(api, windows)), \
                patch.object(window_control.time, 'sleep'):
            result = window_control.window_focus(Path('client.exe'))
        self.assertTrue(result['ok'])
        api.SetForegroundWindow.assert_called_once_with(42)

    def test_unmatched_handle_cannot_activate_another_window(self):
        api = Mock()
        windows = [{'pid': 10, 'window': 42, 'title': 'Client'}]
        with patch.object(window_control, 'windows_for', return_value=(api, windows)):
            result = window_control.window_focus(Path('client.exe'), 999)
        self.assertFalse(result['ok'])
        api.SetForegroundWindow.assert_not_called()

    def test_os_acceptance_alone_is_not_foreground_success(self):
        api = Mock()
        api.IsIconic.return_value = False
        api.SetForegroundWindow.return_value = True
        api.SendMessageTimeoutW.return_value = 1
        api.GetForegroundWindow.return_value = 7
        windows = [{'pid': 10, 'window': 42, 'title': 'Client'}]
        with patch.object(window_control, 'windows_for', return_value=(api, windows)), \
                patch.object(window_control.time, 'monotonic', side_effect=[0, 2]):
            result = window_control.window_focus(Path('client.exe'))
        self.assertFalse(result['ok'])
        self.assertTrue(result['os_accepted'])


if __name__ == '__main__':
    unittest.main()
