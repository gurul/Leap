from leapinput import camera


def _with(monkeypatch, names):
    monkeypatch.setattr(camera, "camera_names", lambda: names)
    return camera.pick_camera_index()


def test_obsbot_beats_builtin(monkeypatch):
    names = ["OBSBOT Tiny 3 StreamCamera", "Camo Camera", "MacBook Pro Camera"]
    assert _with(monkeypatch, names) == 0


def test_obsbot_found_behind_virtual(monkeypatch):
    names = ["Camo Camera", "MacBook Pro Camera", "OBSBOT Tiny 3 StreamCamera"]
    assert _with(monkeypatch, names) == 2


def test_builtin_when_no_obsbot(monkeypatch):
    assert _with(monkeypatch, ["Camo Camera", "MacBook Pro Camera"]) == 1


def test_zero_when_nothing_known(monkeypatch):
    assert _with(monkeypatch, []) == 0
