"""Tutorial step machine — every transition driven by the real event types."""

from leapinput.commands import Command, CommandEvent
from leapinput.gestures import Intent, IntentEvent
from leapinput.tutorial import TutorialTracker


def intent(tr, name, **data):
    tr.on_intent(IntentEvent(name, 0.0, None, data))


def command(tr, name, **data):
    tr.on_command(CommandEvent(name, 0.0, data))


def test_the_full_walkthrough_completes_in_order():
    tr = TutorialTracker()
    assert tr.current.title == "Show your hand"
    intent(tr, Intent.ENGAGE)

    assert tr.current.title == "Point and move"
    for _ in range(30):
        intent(tr, Intent.POINT_MOVE)

    assert tr.current.title == "Pinch to click"
    intent(tr, Intent.SELECT_DOWN)
    intent(tr, Intent.SELECT_UP)

    assert tr.current.title == "Fist to drag"
    intent(tr, Intent.GRAB_DOWN)
    for _ in range(12):
        intent(tr, Intent.POINT_MOVE)
    intent(tr, Intent.GRAB_UP)

    assert tr.current.title == "Open hand to park"
    intent(tr, Intent.CLUTCH_UP)

    assert tr.current.title == "Frame a pane"
    command(tr, Command.NEW_PANE, rect=(0.2, 0.2, 0.8, 0.8))

    assert tr.current.title == "OK for Mission Control"
    command(tr, Command.MISSION_CONTROL)

    assert tr.current.title == "ILY to pause"
    command(tr, Command.TOGGLE, enabled=False)

    assert tr.current.title == "ILY to resume"
    command(tr, Command.TOGGLE, enabled=True)

    assert tr.done


def test_out_of_order_events_do_not_advance():
    tr = TutorialTracker()
    # Still on step 0: none of these are "show your hand".
    command(tr, Command.NEW_PANE)
    intent(tr, Intent.SELECT_DOWN)
    intent(tr, Intent.SELECT_UP)
    intent(tr, Intent.POINT_MOVE)
    assert tr.index == 0


def test_a_click_needs_both_edges():
    tr = TutorialTracker()
    intent(tr, Intent.ENGAGE)
    for _ in range(30):
        intent(tr, Intent.POINT_MOVE)
    assert tr.current.title == "Pinch to click"
    intent(tr, Intent.SELECT_UP)        # up without down: not a click
    assert tr.current.title == "Pinch to click"


def test_drag_counts_only_moves_while_grabbed():
    tr = TutorialTracker()
    intent(tr, Intent.ENGAGE)
    for _ in range(30):
        intent(tr, Intent.POINT_MOVE)
    intent(tr, Intent.SELECT_DOWN)
    intent(tr, Intent.SELECT_UP)
    assert tr.current.title == "Fist to drag"
    for _ in range(50):                 # moving without the fist: no progress
        intent(tr, Intent.POINT_MOVE)
    assert tr.current.count == 0
    intent(tr, Intent.GRAB_DOWN)
    for _ in range(12):
        intent(tr, Intent.POINT_MOVE)
    assert tr.current.title == "Open hand to park"
