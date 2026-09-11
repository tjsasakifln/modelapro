"""psutil is a direct runtime dependency used by the shipped monitor."""

from backend.monitor import SystemMonitor


def test_system_monitor_uses_psutil():
    stats = SystemMonitor.get_system_stats()
    assert "cpu_percent" in stats
    assert "memory_percent" in stats
    assert 0.0 <= float(stats["cpu_percent"]) <= 100.0
    assert 0.0 <= float(stats["memory_percent"]) <= 100.0
