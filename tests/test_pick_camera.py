from leapinput import camera


def _with(monkeypatch, names, ffmpeg="/opt/homebrew/bin/ffmpeg"):
    # pick_camera_index skips an OBSBOT when ffmpeg is missing (2026-11-15),
    # so pin ffmpeg's presence rather than inherit this machine's.
    from leapinput import ffmpegcam
    monkeypatch.setattr(ffmpegcam, "ffmpeg_path", lambda: ffmpeg)
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
